# -*- encoding: utf-8 -*-
"""HTTP client for api requests.

This is pluggable into the IPFS Api client and will hopefully be supplemented
by an asynchronous version.
"""
from __future__ import absolute_import

import abc
import contextlib
import functools
import re
import tarfile
from six.moves import http_client

import requests
import six

from . import encoding
from . import exceptions


def pass_defaults(func):
    """Decorator that returns a function named wrapper.

    When invoked, wrapper invokes func with default kwargs appended.

    Parameters
    ----------
    func : callable
        The function to append the default kwargs to
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        merged = {}
        merged.update(self.defaults)
        merged.update(kwargs)
        return func(self, *args, **merged)
    return wrapper


def _notify_stream_iter_closed():
	pass  # Mocked by unit tests to determine check for proper closing


class StreamDecodeIterator(object):
	"""
	Wrapper around `Iterable` that allows the iterable to be used in a
	context manager (`with`-statement) allowing for easy cleanup.
	"""
	def __init__(self, response, parser):
		self._response = response
		self._parser   = parser
		self._response_iter = response.iter_content(chunk_size=None)
		self._parser_iter   = None

	def __iter__(self):
		return self

	def __next__(self):
		while True:
			# Try reading for current parser iterator
			if self._parser_iter is not None:
				try:
					result = next(self._parser_iter)
					
					# Detect late error messages that occured after some data
					# has already been sent
					if isinstance(result, dict) and result.get("Type") == "error":
						msg = result["Message"]
						raise exceptions.PartialErrorResponse(msg, None, [])
					
					return result
				except StopIteration:
					self._parser_iter = None

					# Forward exception to caller if we do not expect any
					# further data
					if self._response_iter is None:
						raise

			try:
				data = next(self._response_iter)

				# Create new parser iterator using the newly recieved data
				self._parser_iter = iter(self._parser.parse_partial(data))
			except StopIteration:
				# No more data to receive – destroy response iterator and
				# iterate over the final fragments returned by the parser
				self._response_iter = None
				self._parser_iter   = iter(self._parser.parse_finalize())

	#PY2: Old iterator syntax
	def next(self):
		return self.__next__()

	def __enter__(self):
		return self

	def __exit__(self, *a):
		self.close()

	def close(self):
		# Clean up any open iterators first
		if self._response_iter is not None:
			self._response_iter.close()
		if self._parser_iter is not None:
			self._parser_iter.close()
		self._response_iter = None
		self._parser_iter   = None

		# Clean up response object and parser
		if self._response is not None:
			self._response.close()
		self._response = None
		self._parser   = None

		_notify_stream_iter_closed()


def stream_decode_full(response, parser):
	with StreamDecodeIterator(response, parser) as response_iter:
		# Collect all responses
		result = list(response_iter)
		
		# Return byte streams concatenated into one message, instead of split
		# at arbitrary boundaries
		if parser.is_stream:
			return b"".join(result)
		return result


class HTTPClient(object):
    """An HTTP client for interacting with the IPFS daemon.

    Parameters
    ----------
    host : str
        The host the IPFS daemon is running on
    port : int
        The port the IPFS daemon is running at
    base : str
        The path prefix for API calls
    defaults : dict
        The default parameters to be passed to
        :meth:`~ipfshttpclient.http.HTTPClient.request`
    """

    __metaclass__ = abc.ABCMeta

    def __init__(self, host, port, base, **defaults):
        self.host = host
        self.port = port
        if not re.match('^https?://', host.lower()):
            host = 'http://' + host

        self.base = '%s:%s/%s' % (host, port, base)

        self.defaults = defaults
        self._session = None

    def _do_request(self, *args, **kwargs):
        try:
            if self._session:
                return self._session.request(*args, **kwargs)
            else:
                return requests.request(*args, **kwargs)
        except (requests.ConnectTimeout, requests.Timeout) as error:
            six.raise_from(exceptions.TimeoutError(error), error)
        except requests.ConnectionError as error:
            six.raise_from(exceptions.ConnectionError(error), error)
        except http_client.HTTPException as error:
            six.raise_from(exceptions.ProtocolError(error), error)

    def _do_raise_for_status(self, response):
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            content = []
            try:
                decoder = encoding.get_encoding("json")
                for chunk in response.iter_content(chunk_size=None):
                    content += list(decoder.parse_partial(chunk))
                content += list(decoder.parse_finalize())
            except exceptions.DecodingError:
                pass
            
            # If we have decoded an error response from the server,
            # use that as the exception message; otherwise, just pass
            # the exception on to the caller.
            if len(content) == 1 \
            and isinstance(content[0], dict) \
            and "Message" in content[0]:
                msg = content[0]["Message"]
                six.raise_from(exceptions.ErrorResponse(msg, error), error)
            else:
                six.raise_from(exceptions.StatusError(error), error)

    def _request(self, method, url, params, parser, stream=False, files=None,
                 headers={}, data=None, timeout=120):
        # Do HTTP request (synchronously)
        res = self._do_request(method, url, params=params, stream=stream,
                               files=files, headers=headers, data=data, timeout=timeout)

        # Raise exception for response status
        # (optionally incorpating the response message, if applicable)
        self._do_raise_for_status(res)

        if stream:
            # Decode each item as it is read
            return StreamDecodeIterator(res, parser)
        else:
            # Decode received item immediately
            return stream_decode_full(res, parser)

    @pass_defaults
    def request(self, path,
                args=[], files=[], opts={}, stream=False,
                decoder=None, headers={}, data=None, timeout=120):
        """Makes an HTTP request to the IPFS daemon.

        This function returns the contents of the HTTP response from the IPFS
        daemon.

        Raises
        ------
        ~ipfshttpclient.exceptions.ErrorResponse
        ~ipfshttpclient.exceptions.ConnectionError
        ~ipfshttpclient.exceptions.ProtocolError
        ~ipfshttpclient.exceptions.StatusError
        ~ipfshttpclient.exceptions.TimeoutError

        Parameters
        ----------
        path : str
            The REST command path to send
        args : list
            Positional parameters to be sent along with the HTTP request
        files : Union[str, io.RawIOBase, collections.abc.Iterable]
            The file object(s) or path(s) to stream to the daemon
        opts : dict
            Query string paramters to be sent along with the HTTP request
        decoder : str
            The encoder to use to parse the HTTP response
        timeout : float
            How many seconds to wait for the server to send data
            before giving up
            
            Defaults to 120
        kwargs : dict
            Additional arguments to pass to :mod:`requests`
        """
        url = self.base + path

        params = []
        params.append(('stream-channels', 'true'))
        for opt in opts.items():
            params.append(opt)
        for arg in args:
            params.append(('arg', arg))

        method = 'post' if (files or data) else 'get'

        parser = encoding.get_encoding(decoder if decoder else "none")

        return self._request(method, url, params, parser, stream,
                             files, headers, data, timeout=timeout)

    @pass_defaults
    def download(self, path, args=[], filepath=None, opts={},
                 compress=True, timeout=120, **kwargs):
        """Makes a request to the IPFS daemon to download a file.

        Downloads a file or files from IPFS into the current working
        directory, or the directory given by ``filepath``.

        Raises
        ------
        ~ipfshttpclient.exceptions.ErrorResponse
        ~ipfshttpclient.exceptions.ConnectionError
        ~ipfshttpclient.exceptions.ProtocolError
        ~ipfshttpclient.exceptions.StatusError
        ~ipfshttpclient.exceptions.TimeoutError

        Parameters
        ----------
        path : str
            The REST command path to send
        filepath : str
            The local path where IPFS will store downloaded files

            Defaults to the current working directory.
        args : list
            Positional parameters to be sent along with the HTTP request
        opts : dict
            Query string paramters to be sent along with the HTTP request
        compress : bool
            Whether the downloaded file should be GZip compressed by the
            daemon before being sent to the client
        timeout : float
            How many seconds to wait for the server to send data
            before giving up
            
            Defaults to 120
        kwargs : dict
            Additional arguments to pass to :mod:`requests`
        """
        url = self.base + path
        wd = filepath or '.'

        params = []
        params.append(('stream-channels', 'true'))
        params.append(('archive', 'true'))
        if compress:
            params.append(('compress', 'true'))

        for opt in opts.items():
            params.append(opt)
        for arg in args:
            params.append(('arg', arg))

        method = 'get'

        res = self._do_request(method, url, params=params, stream=True,
                               timeout=timeout, **kwargs)

        self._do_raise_for_status(res)

        # try to stream download as a tar file stream
        mode = 'r|gz' if compress else 'r|'

        with tarfile.open(fileobj=res.raw, mode=mode) as tf:
            tf.extractall(path=wd)

    @contextlib.contextmanager
    def session(self):
        """A context manager for this client's session.

        This function closes the current session when this client goes out of
        scope.
        """
        self._session = requests.session()
        yield
        self._session.close()
        self._session = None
