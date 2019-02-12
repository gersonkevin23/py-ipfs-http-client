# -*- coding: utf-8 -*-
from __future__ import absolute_import

from . import base


class SubChannel:
	"""
	Wrapper for a pubsub subscription object that allows for easy
	closing of subscriptions.
	"""
	def __init__(self, sub):
		self.__sub = sub

	def read_message(self):
		return next(self.__sub)

	def __iter__(self):
		return self.__sub

	def close(self):
		self.__sub.close()

	def __enter__(self):
		return self

	def __exit__(self, *a):
		self.close()


class Section(base.SectionBase):
	@base.returns_single_item
	def ls(self, **kwargs):
		"""Lists subscribed topics by name

		This method returns data that contains a list of
		all topics the user is subscribed to. In order
		to subscribe to a topic ``pubsub.sub`` must be called.

		.. code-block:: python

			# subscribe to a channel
			>>> with client.pubsub.sub("hello") as sub:
			...     client.pubsub.ls()
			{
				'Strings' : ["hello"]
			}

		Returns
		-------
			dict : Dictionary with the key "Strings" who's value is an array of
				   topics we are subscribed to
		"""
		return self._client.request('/pubsub/ls', decoder='json', **kwargs)
	
	
	@base.returns_single_item
	def peers(self, topic=None, **kwargs):
		"""List the peers we are pubsubbing with.

		Lists the id's of other IPFS users who we
		are connected to via some topic. Without specifying
		a topic, IPFS peers from all subscribed topics
		will be returned in the data. If a topic is specified
		only the IPFS id's of the peers from the specified
		topic will be returned in the data.

		.. code-block:: python

			>>> client.pubsub.peers()
			{'Strings':
					[
						'QmPbZ3SDgmTNEB1gNSE9DEf4xT8eag3AFn5uo7X39TbZM8',
						'QmQKiXYzoFpiGZ93DaFBFDMDWDJCRjXDARu4wne2PRtSgA',
						...
						'QmepgFW7BHEtU4pZJdxaNiv75mKLLRQnPi1KaaXmQN4V1a'
					]
			}

			## with a topic

			# subscribe to a channel
			>>> with client.pubsub.sub('hello') as sub:
			...     client.pubsub.peers(topic='hello')
			{'String':
					[
						'QmPbZ3SDgmTNEB1gNSE9DEf4xT8eag3AFn5uo7X39TbZM8',
						...
						# other peers connected to the same channel
					]
			}

		Parameters
		----------
		topic : str
			The topic to list connected peers of
			(defaults to None which lists peers for all topics)

		Returns
		-------
			dict : Dictionary with the ke "Strings" who's value is id of IPFS
				   peers we're pubsubbing with
		"""
		args = (topic,) if topic is not None else ()
		return self._client.request('/pubsub/peers', args, decoder='json', **kwargs)
	
	
	@base.returns_no_item
	def publish(self, topic, payload, **kwargs):
		"""Publish a message to a given pubsub topic

		Publishing will publish the given payload (string) to
		everyone currently subscribed to the given topic.

		All data (including the id of the publisher) is automatically
		base64 encoded when published.

		.. code-block:: python

			# publishes the message 'message' to the topic 'hello'
			>>> client.pubsub.publish('hello', 'message')
			[]

		Parameters
		----------
		topic : str
			Topic to publish to
		payload : Data to be published to the given topic

		Returns
		-------
			list : empty list
		"""
		args = (topic, payload)
		return self._client.request('/pubsub/pub', args, decoder='json', **kwargs)
	
	
	def subscribe(self, topic, discover=False, **kwargs):
		"""Subscribe to mesages on a given topic

		Subscribing to a topic in IPFS means anytime
		a message is published to a topic, the subscribers
		will be notified of the publication.

		The connection with the pubsub topic is opened and read.
		The Subscription returned should be used inside a context
		manager to ensure that it is closed properly and not left
		hanging.

		.. code-block:: python

			>>> sub = client.pubsub.subscribe('testing')
			>>> with client.pubsub.subscribe('testing') as sub:
			# publish a message 'hello' to the topic 'testing'
			...	client.pubsub.publish('testing', 'hello')
			... for message in sub:
			...     print(message)
			...     # Stop reading the subscription after
			...     # we receive one publication
			...     break
			{'from': '<base64encoded IPFS id>',
			 'data': 'aGVsbG8=',
			 'topicIDs': ['testing']}

			# NOTE: in order to receive published data
			# you must already be subscribed to the topic at publication
			# time.

		Parameters
		----------
		topic : str
			Name of a topic to subscribe to

		discover : bool
			Try to discover other peers subscibed to the same topic
			(defaults to False)

		Returns
		-------
			Generator wrapped in a context
			manager that maintains a connection
			stream to the given topic.
		"""
		args = (topic, discover)
		return SubChannel(self._client.request('/pubsub/sub', args, stream=True, decoder='json'))