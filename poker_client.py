from twisted.internet import reactor
from twisted.internet.endpoints import connectProtocol, TCP4ClientEndpoint
from basicpokerp2p import Player
from web3 import Web3, HTTPProvider
import sys, string, random

def runclient(priv, w3, randomness, connect_host, connect_port):
    point = TCP4ClientEndpoint(reactor, connect_host, connect_port)
    d = connectProtocol(point, Player(priv, w3, randomness, 0, 0, 0, 0, True))
    reactor.run()

if __name__ == "__main__":
	if len(sys.argv) < 4:
		raise ValueError("Must provide command line arguments: <ip:port> <infura url> <private key>")
	print()
	print("Welcome to pokerP2P (beta)")
	print("peer to peer one card poker on the ethereum (ropsten test) network")
	print()
	args = sys.argv[1:]
	connect_info = args[0].split(':')
	host = connect_info[0]
	port = int(connect_info[1])
	w3 = Web3(HTTPProvider(args[1]))
	priv = args[2]
	randomness = ''.join([random.choice(string.ascii_letters+string.digits) for _ in range(25)]).encode()
	print(f"... attempting to connect to {host} on port {port} ...")
	runclient(priv, w3, randomness, host, port)