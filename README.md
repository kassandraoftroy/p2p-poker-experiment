# PokerP2P

This is a beta/demo version of the first verifiably fair peer to peer card game without a trusted third party for shuffling/dealing/revealing cards OR for managing buy ins and cash outs. The game is entirely decentralized from start to finish and involves no outside parties, just the two opponents who want to play a fair game, and the ethereum virtual machine.

The game is an extremely simplified version of "poker" -- each player is dealt one card and the players bet on who has the higher card. In the case of a tie suit acts as a tiebreaker (from lowest to highest: clubs, diamonds, hearts, spades). Players can play as many hands as they like or until someone goes broke. There is no buying back into a table -- each table has a fixed buy in and to play again you'll need to open a new table.

### Demo

To try a complete live demo of the game on the Ethereum Ropsten Test Network (NOT real money) here are the steps:

1. Genereate an ethereum keypair (preferably a fresh one that does not hold real ether).
2. Get some Ropsten Ether from a faucet (google ropsten faucet...)
3. Clone this repository
4. Get a free infura.io account. Whitelist the address that you funded with ropsten ether in steps 1-2. Also whitelist these contract addresses: `0x34cC3183bff750Fb6b2fafA0fcdEFEfb6764873B` and `0x5fB5EDF7255e8CF168a41AD67472a76bb8304acb`
5. Make sure you have a copy of the raw Hex private key for your (ropsten) funded address.

Now the steps become different for each player. If you are the "host" peer (the one who runs the application first and waits for a connection):

6. Make sure you are forwarding the port from which you will run the server (either configure your router or use a virtual machine)
7. cd into the root of this repository. Run this command:

``` 
python3 poker_server.py <port> <your infura ropsten url> <your hex private key> <buy in amount (in ether)>
```

8. Give your opponent the ip:port to connect to the server i.e. (`0.0.0.0:8000`). Wait for an incoming connection!


If you are the Client peer then:

6. Retreive the ip:port of the server to connect to.
7. cd into the root of this repository. Run this command:

``` 
python3 poker_client.py <ip:port> <your infura ropsten url> <your hex private key>
```

The UI is extremely rudimentary, lackluster, and probably buggy. This UI is really only to serve the purpose of allowing somewhat easy interaction with the contract to verify that it works as it should. An in browser version should be in the works to make the game and contract much more accessible to a wide audience. For now if you know a bit of python and the basics of cryptocurrency you should be able to get the demo up and running fairly quickly.

### State Channel Considerations

The solidity contracts utilize ethereum state channel technology, so peers in a game can play in realtime without wasting fees or time by pushing every state change to the blockchain. Instead players only report to the blockchain when cashing into and out of a table and mantain their state P2P. There are some careful consideraitons about cashing out and dispute resolution: make sure you report your very last game state to the contract ASAP so as not to be duped by an opponent looking to cheat by reporting an earlier state and hoping you don't dispute it in time. In a more legitimate setting the timeframe for these dispute resoultions (which can be chosen by the players themselves) should be sufficiently long so that if a player tries any malicious reporting, it can be corrected even in worst case scenarios with very bad network conditions and slow processing times. If a game is played out to completion, there is no need for dispute resolution and cashout happen instantaneously.

If you disconnect during play there is currently no way to rejoin the game and keep playing. You can use the chached game information that was written to a file in the gamestate folder and the settlement.py script to make sure that a fair cash-out still occurs (no you cannot save yourself money by disconnecting right when you realize you are going to lose the hand).

### Mental poker

How can a public blockchain (where all state is public knowledge) and a decentralized group of players who don't trust one another ever shuffle and deal cards in a verifiably random and fair way? Check out the mentalpoker repository to more information on this topic.

### Contact

contact actiontoken@protonmail.com for questions, comments, etc, or if you are simply interested in the project and want to be a part of the development.
