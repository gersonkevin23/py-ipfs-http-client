# _*_ coding: utf-8 -*-
import ipfshttpclient

import conftest


def test_ipfs_node_available():
	"""
	Dummy test to ensure that running the tests without a daemon produces a failure, since we
	think it's unlikely that people running tests want this
	"""
	addr = "[{0}]:{1}".format(ipfshttpclient.DEFAULT_HOST, ipfshttpclient.DEFAULT_PORT)
	assert conftest.is_available(), "Functional tests require an IPFS node to be available at: " + addr


def test_add_json(client, cleanup_pins):
	data = {"Action": "Open", "Type": "PR", "Name": "IPFS", "Pubkey": 7}
	res = client.add_json(data)

	assert data == client.get_json(res)

	# have to test the string added to IPFS, deserializing JSON will not
	# test order of keys
	assert '{"Action":"Open","Name":"IPFS","Pubkey":7,"Type":"PR"}' == client.cat(res).decode("utf-8")


def test_add_get_pyobject(client, cleanup_pins):
	data = [-1, 3.14, u"Hän€", b"23"]
	res = client.add_pyobj(data)

	assert data == client.get_pyobj(res)