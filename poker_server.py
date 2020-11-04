from twisted.internet import reactor
from basicpokerp2p import PlayerFactory
from web3 import Web3, HTTPProvider
import sys, string, random

def runserver(priv, w3, randomness, buy_in, duration, join_duration, dispute_duration, my_port):
    f = PlayerFactory(priv, w3, randomness, buy_in, duration, join_duration, dispute_duration)
    reactor.listenTCP(my_port, f)
    reactor.run()

if __name__ == "__main__":
	if len(sys.argv) < 5:
		raise ValueError("Must provide command line arguments: <port> <infura url> <private key> <buy in amount (in ether)>")
	print()
	print("Welcome to pokerP2P (beta)")
	print("peer to peer one card poker on the ethereum (ropsten test) network")
	print()
	args = sys.argv[1:]
	port = int(args[0])
	w3 = Web3(HTTPProvider(args[1]))
	priv = args[2]
	buy_in = int(float(args[3])*Web3.toWei(1, 'ether'))
	duration = 3600
	join_duration = 600
	dispute_duration = 900
	if len(args) > 4:
		duration = int(args[4])
	if len(args) > 5:
		join_duration = int(args[5])
	if len(args) > 6:
		dispute_duration = int(args[6])
	randomness = ''.join([random.choice(string.ascii_letters+string.digits) for _ in range(25)]).encode()
	print("... waiting for incoming connections ...")
	runserver(priv, w3, randomness, buy_in, duration, join_duration, dispute_duration, port)

	


