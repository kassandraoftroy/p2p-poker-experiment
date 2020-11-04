from twisted.internet.protocol import Protocol, Factory
from contract_control import HeadsUpContract, HighCardPokerContract
from eth_abi import encode_abi, decode_abi
from web3 import Web3
from ecdsa import ellipticcurve
import json, random, hashlib, binascii, time, os
from mentalpoker import *

cards = ['2c', '2d', '2h', '2s', '3c', '3d', '3h', '3s', '4c', '4d', '4h', '4s', '5c', '5d', '5h', '5s', '6c', '6d', '6h', '6s', '7c', '7d', '7h', '7s', '8c', '8d', '8h', '8s', '9c', '9d', '9h', '9s', 'Tc', 'Td', 'Th', 'Ts', 'Jc', 'Jd', 'Jh', 'Js', 'Qc', 'Qd', 'Qh', 'Qs', 'Kc', 'Kd', 'Kh', 'Ks', 'Ac', 'Ad', 'Ah', 'As']
empty_address = "0x0000000000000000000000000000000000000000"
ether = Web3.toWei(1, 'ether')
gamedir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamestate")
if not os.path.exists(gamedir):
    os.mkdir(gamedir)

class Player(Protocol):
    def __init__(self, priv, w3, randomness, buy_in, duration, join_duration, dispute_duration, client):
        self.state = "INIT"
        self.remote_address = None
        self.players = None
        self.w3 = w3
        self.account = self.w3.eth.account.privateKeyToAccount(priv)
        self.client = client
        self.poker_contract = HighCardPokerContract(w3, contract_address="0x34cC3183bff750Fb6b2fafA0fcdEFEfb6764873B")
        self.table_contract = HeadsUpContract(priv, w3, contract_address="0x5fB5EDF7255e8CF168a41AD67472a76bb8304acb")
        self.randomness = randomness
        self.sessionID = None
        self.buy_in = buy_in
        self.duration = duration
        self.join_duration = join_duration
        self.dispute_duration = dispute_duration
        self.default_gas = 3000000
        self.signed_states = [] 
        self.dealer = DealerEC(cards=cards)
        self.game_basics = {}
        self.backup_file = None
        self.current_deck = None
        self.current_state = [0, [0,4], [self.buy_in, self.buy_in, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0], [empty_address, empty_address]]
        self.current_state_sigs = {}
        self.current_recv = b''
    
    def dataReceived(self, data):
        self.current_recv += data
        if data.decode()[-1] != '\n':
            return
        else:
            line = self.current_recv.strip()
            self.current_recv = b''
            msgtype = json.loads(line)['msgtype']
            if msgtype == "hello":
                self.handle_hello(line)
            if msgtype == "create":
                self.handle_create(line)
            if msgtype == "join":
                self.handle_join(line)
            if msgtype == "shuffle":
                self.handle_shuffle(line)
            if msgtype == "hand":
                self.handle_hand(line)
            if msgtype == "handover":
                self.handover(line)

    def connectionMade(self):
        peer = self.transport.getPeer()
        print("Connection from", peer.host+":"+str(peer.port))
        if self.client:
            self.send_hello()

    def connectionLost(self, reason):
        print(self.remote_address, "disconnected")
        current_encoded = self.poker_contract.encode_state(*self.current_state)
        if (len(self.current_state_sigs) == 1) and (binascii.hexlify(current_encoded).decode()!=self.signed_states[-1]['state']):
            unfinished = {'state': binascii.hexlify(current_encoded).decode(), 'signature': self.current_state_sigs[self.account.address]}
            game = json.dumps({'game': self.game_basics, 'states': self.signed_states, 'unfinished': unfinished})
            with open(self.backup_file, "w") as f:
                f.write(game)

    def send_hello(self):
        msg = {'address': self.account.address, 'sessionID': self.randomness.decode(), 'msgtype': 'hello'}
        if not self.client:
            msg['buyin'] = self.buy_in
            msg['duration'] = self.duration
            msg['join_duration'] = self.join_duration
            msg['dispute_duration'] = self.dispute_duration
        hello = json.dumps(msg)
        hello = hello + "\n"
        self.transport.write(str.encode(hello))
        
    def handle_hello(self, hello):
        hello = json.loads(hello.decode('utf-8'))
        address = hello["address"]
        if self.remote_address != None and self.remote_address != address:
            print(f"received hello from {address} while in game with {self.remote_address}")
            return
        if address == self.account.address:
            print("Connected to myself.")
            self.transport.loseConnection()
            self.remote_address = None
            return
        if self.state == "INIT":
            self.remote_address = hello["address"]
            self.state = "READY"
            print("opponent_address:", self.remote_address)
            self.players = [self.account.address, self.remote_address]
            if int(self.players[0][2:], 16) > int(self.players[1][2:], 16):
                self.players = [self.remote_address, self.account.address]
            if self.client:
                self.sessionID = hashlib.sha256(self.randomness+str.encode(hello['sessionID'])).digest()
                self.backup_file = os.path.join(gamedir, binascii.hexlify(self.sessionID).decode()+'.pkr')
                self.buy_in = hello['buyin']
                self.duration = hello['duration']
                self.dispute_duration = hello['dispute_duration']
                self.join_duration = hello['join_duration']
                self.current_state[2][0] = self.buy_in
                self.current_state[2][1] = self.buy_in
                self.send_create()
            else:
                self.sessionID = hashlib.sha256(str.encode(hello['sessionID'])+self.randomness).digest()
                self.backup_file = os.path.join(gamedir, binascii.hexlify(self.sessionID).decode()+'.pkr')
                self.send_hello()

    def send_create(self):
        print(f"{self.remote_address} wants to open a table with you. buy in: {self.buy_in/ether} eth; duration: {self.duration}; dispute duration: {self.dispute_duration}")
        i=input("press enter to accept invitation (type `exit` to reject)")
        if i=="exit":
            raise ValueError("you quit")
        sig = self.table_contract.sign_new_table(self.players, self.buy_in, self.duration, self.join_duration, self.dispute_duration, self.sessionID)
        create = json.dumps({'v': sig[0], 'r': sig[1], 's': sig[2], 'msgtype': 'create'})
        create = create + "\n"
        self.transport.write(str.encode(create))

    def handle_create(self, create):
        create = json.loads(create.decode('utf-8'))
        recv_sig = [create['v'], create['r'], create['s']]
        sig = self.table_contract.sign_new_table(self.players, self.buy_in, self.duration, self.join_duration, self.dispute_duration, self.sessionID)
        addr2sig = {self.account.address: sig, self.remote_address: recv_sig}
        i=input(f"press enter to open a table against {self.remote_address} with a buy in of {self.buy_in/ether} eth")
        if i == "exit":
            raise ValueError("you quit")
        resp = self.table_contract.open_table_tx(addr2sig, self.players, self.buy_in, self.duration, self.join_duration, self.dispute_duration, self.sessionID, self.default_gas)
        print("open table tx:", binascii.hexlify(resp))
        print("waiting for opponent confirmation to begin...")
        print()
        self.game_basics = {'players': self.players, 'start_time': int(time.time()), 'duration': self.duration, 'dispute_duration': self.dispute_duration, 'tableID': binascii.hexlify(self.table_contract.tableID).decode(), 'sessionID': binascii.hexlify(self.sessionID).decode()}
        join = json.dumps({'tx': binascii.hexlify(resp).decode('utf-8'), 'msgtype':'join', 'buyin': self.buy_in})
        join = join + "\n"
        self.transport.write(str.encode(join))

    def handle_join(self, join):
        join = json.loads(join.decode('utf-8'))
        print(f"{self.remote_address} opened your table, please wait for game to be confirmed on the blockchain...")
        wait = True
        self.game_basics = {'players': self.players, 'start_time': int(time.time()), 'duration': self.duration, 'dispute_duration': self.dispute_duration, 'tableID': binascii.hexlify(self.table_contract.tableID).decode(), 'sessionID': binascii.hexlify(self.sessionID).decode()}
        while wait:
            try:
                self.table_contract.contract.functions.getTableOverview(self.table_contract.tableID).call()
                wait = False
            except:
                print("waiting...")
                time.sleep(5)
        resp = self.table_contract.join_table_tx(self.players, join['buyin'], self.sessionID, self.default_gas)
        print("you joined the game! see tx here:", binascii.hexlify(resp))
        print()
        self.start_shuffle()

    def start_shuffle(self):
        self.current_deck = self.dealer.shuffle(self.dealer.new_deck)
        send_deck = [point2hex(i) for i in self.current_deck]
        shuffle_1 = json.dumps({'msgtype':'shuffle', 'round': 1, 'deck': send_deck})
        shuffle_1 = shuffle_1 + "\n"
        self.transport.write(str.encode(shuffle_1))

    def handle_shuffle(self, shuffle):
        shuffle = json.loads(shuffle.decode('utf-8'))
        if shuffle['round'] == 1:
            recv_deck = [hex2point(i) for i in shuffle['deck']]
            self.current_deck = self.dealer.shuffle(recv_deck)
            send_deck = [point2hex(i) for i in self.current_deck[:2]]
            shuffle_2 = json.dumps({'msgtype':'shuffle', 'round': 2, 'deck': send_deck})
            shuffle_2 = shuffle_2 + "\n"
            self.transport.write(str.encode(shuffle_2))
        elif shuffle['round'] == 2:
            recv_deck = [hex2point(i) for i in shuffle['deck']]
            self.current_deck = self.dealer.deal(recv_deck)
            send_deck = [point2hex(i) for i in self.current_deck]
            reveal_idx = 1 if self.players[0]==self.account.address else 0
            shuffle_3 = json.dumps({'msgtype':'shuffle', 'round': 3, 'deck': send_deck, 'key': self.dealer.get_card_key(reveal_idx).alpha})
            shuffle_3 = shuffle_3 + "\n"
            self.transport.write(str.encode(shuffle_3))
        elif shuffle['round'] == 3:
            recv_deck = [hex2point(i) for i in shuffle['deck']]
            self.current_deck = self.dealer.deal(recv_deck)
            self.start_hand(shuffle['key'])
        elif shuffle['round'] == 4:
            recv_deck = [hex2point(i) for i in shuffle['deck']]
            self.current_deck = recv_deck
            self.start_hand(shuffle['key'])
        else:
            print("bad shuffle message:", shuffle)
            raise ValueError("Unreadable message-- probably go to cash out scenario...")

    def start_hand(self, recv_key):
        if (((self.current_state[0]+1)%2 == 0) and (self.players[0]==self.account.address)) or (((self.current_state[0]+1)%2 != 0) and (self.players[0]!=self.account.address)):
            print("... passing back not my turn to act first...")
            reveal_idx = 1 if self.players[0]==self.account.address else 0
            pass_msg = json.dumps({'msgtype':'shuffle', 'round': 4, 'deck': [point2hex(i) for i in self.current_deck], 'key': self.dealer.get_card_key(reveal_idx).alpha})
            pass_msg = pass_msg + "\n"
            self.transport.write(str.encode(pass_msg))
        else:
            current_encoded = self.poker_contract.encode_state(*self.current_state)
            new_state = [self.current_state[0]+1, [1, None], [None, None, 3*(self.buy_in//100), self.buy_in//100], [self.current_deck[0].x(), self.current_deck[0].y(), 0, None, self.current_deck[1].x(), self.current_deck[1].y(), None, 0], [self.account.address, empty_address]]
            if self.players[0]==self.account.address:
                card = self.dealer.reveal_card(self.current_deck[0], [self.dealer.get_card_key(0), ECPrivateKey(alpha=recv_key)])
                new_state[2][0] = self.current_state[2][0]-self.buy_in//100
                new_state[2][1] = self.current_state[2][1]-self.buy_in//50
                new_state[3][3] = recv_key
                new_state[3][6] = self.dealer.get_card_key(1).alpha
                print("your card:", card, "your stack:", new_state[2][0]/ether, "opp stack:", new_state[2][1]/ether)
            else:
                card = self.dealer.reveal_card(self.current_deck[1], [self.dealer.get_card_key(1), ECPrivateKey(alpha=recv_key)])
                new_state[2][0] = self.current_state[2][0]-self.buy_in//50
                new_state[2][1] = self.current_state[2][1]-self.buy_in//100
                new_state[3][3] = self.dealer.get_card_key(0).alpha
                new_state[3][6] = recv_key
                print("your card:", card, "your stack:", new_state[2][1]/ether, "opp stack:", new_state[2][0]/ether)
            print("pot:", new_state[2][2]/ether, "to call:", new_state[2][3]/ether)
            continue_ = False
            new_encoded = None
            i = 0
            while not continue_:
                i += 1
                action_type = input("[fold=0, call=1, raise=2]: ")
                if i > 8:
                    raise ValueError("too many mistakes")
                if action_type=="0":
                    new_state[1][1] = 0
                    new_state[2][3] = 0
                    new_encoded = self.poker_contract.encode_state(*new_state)
                    valid = self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in)
                    if valid:
                        continue_ = True
                    else:
                        print("invalid state transition??")
                elif action_type=="1":
                    new_state[1][1] = 1
                    new_state[2][3] = 0
                    new_state[2][2] += self.buy_in//100
                    if self.players[0]==self.account.address:
                        new_state[2][0] -= self.buy_in//100
                    else:
                        new_state[2][1] -= self.buy_in//100
                    new_encoded = self.poker_contract.encode_state(*new_state)
                    valid = self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in)
                    if valid:
                        continue_ = True
                    else:
                        print("invalid state transition??")
                elif action_type=="2":
                    raise_str = input(f"call {new_state[2][3]/ether} and raise ({(self.buy_in//50)/ether} min):")
                    try:
                        raise_amnt = Web3.toWei(float(raise_str), 'ether')
                        total_bet = raise_amnt + new_state[2][3]
                        if ((raise_amnt >= self.buy_in//50) or (total_bet==new_state[2][0]) or (total_bet==new_state[2][1])) and (((total_bet<=new_state[2][0]) and (self.players[0] == self.account.address)) or ((total_bet<=new_state[2][1]) and (self.players[1] == self.account.address))):
                            if (self.account.address == self.players[0]) and (raise_amnt > new_state[2][1]):
                                raise_amnt = new_state[2][1]
                                total_bet = raise_amnt + new_state[2][3]
                            elif (self.account.address == self.players[1]) and (raise_amnt > new_state[2][0]):
                                raise_amnt = new_state[2][0]
                                total_bet = raise_amnt + new_state[2][3]                                
                            new_state[1][1] = 2
                            new_state[2][2] += total_bet
                            new_state[2][3] = raise_amnt
                        else:
                            raise ValueError("")
                        if self.players[0]==self.account.address:
                            new_state[2][0] -= total_bet
                        else:
                            new_state[2][1] -= total_bet
                        new_encoded = self.poker_contract.encode_state(*new_state)
                        valid = self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in)
                        if valid:
                            continue_ = True
                        else:
                            print("invalid state transition??")
                    except:
                        print("invalid raise amount entered")
                else:
                    action_type=None
                    print("bad input try again!")
            sig = self.table_contract.sign_table_tx(new_encoded)
            idx = 0
            while not self.table_contract.verify_half_signed_tx(new_encoded, sig, self.account.address):
                idx += 1
                sig = self.table_contract.sign_table_tx(new_encoded)
                if idx > 10:
                    raise ValueError("created invalid signature on state transition")
            hand_msg = json.dumps({'msgtype':'hand', 'type': 1, 'previous_state': binascii.hexlify(current_encoded).decode(), 'next_state': binascii.hexlify(new_encoded).decode(), 'next_v': sig[0], 'next_r': sig[1], 'next_s': sig[2]})
            hand_msg = hand_msg + "\n"
            self.current_state = new_state
            self.current_state_sigs = {self.account.address: sig}
            self.transport.write(str.encode(hand_msg))

    def handle_hand(self, hand):
        hand = json.loads(hand.decode('utf-8'))
        player = self.players[0] if self.players[1]==self.account.address else self.players[1]
        new_encoded = binascii.unhexlify(hand['next_state'])
        prev_encoded = binascii.unhexlify(hand['previous_state'])
        current_encoded = self.poker_contract.encode_state(*self.current_state)
        new_decoded = decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], new_encoded)
        prev_decoded = decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], prev_encoded)
        if prev_encoded != current_encoded:
            raise ValueError("received mismatching state")
        if not self.poker_contract.is_valid_transition(prev_encoded, new_encoded, self.players, self.buy_in):
            raise ValueError("received invalid state transition")
        new_sig = [hand['next_v'], hand['next_r'], hand['next_s']]
        if not self.table_contract.verify_half_signed_tx(new_encoded, new_sig, player):
            raise ValueError("received invalid signature on state transition")
        new_sigs = {self.remote_address: new_sig}
        my_sig = self.table_contract.sign_table_tx(new_encoded)
        new_sigs[self.account.address] = my_sig
        if (new_decoded[0] == self.current_state[0]) and (new_decoded[1][0] != 1):
            prev_sig = [hand['prev_v'], hand['prev_r'], hand['prev_s']]
            if not self.table_contract.verify_half_signed_tx(prev_encoded, prev_sig, player):
                print(prev_sig)
                raise ValueError("received invalid signature on state transition")
            self.current_state_sigs[self.remote_address] = prev_sig
            if len(self.current_state_sigs) != 2:
                raise ValueError("Missing own signature on previous state somehow")
            self.signed_states.append({'state': binascii.hexlify(current_encoded).decode(), 'signatures': self.current_state_sigs})
        elif new_decoded[0] != self.current_state[0]:
            self.current_deck = [ellipticcurve.Point(DEFAULT_CURVE.curve, new_decoded[3][0], new_decoded[3][1]), ellipticcurve.Point(DEFAULT_CURVE.curve, new_decoded[3][4], new_decoded[3][5])]
        self.signed_states.append({'state': binascii.hexlify(new_encoded).decode(), 'signatures': new_sigs})
        game = json.dumps({'game': self.game_basics, 'states': self.signed_states, 'unfinished':''})
        with open(self.backup_file, "w") as f:
            f.write(game)
        self.current_state_sigs = {}
        self.current_state = new_decoded
        new_state = [self.current_state[0],] + [list(self.current_state[i]) for i in range(1, len(self.current_state))]
        new_state[1][0] += 1
        new_state[4][0] = self.account.address
        current_encoded = new_encoded
        new_encoded = None
        if hand["type"] == 1:
            if (self.current_state[1][1] == 2) or (self.current_state[1][1] == 1 and self.current_state[1][0] == 1):
                if self.players[0]==self.account.address:
                    card = self.dealer.reveal_card(self.current_deck[0], [self.dealer.get_card_key(0), ECPrivateKey(alpha=new_state[3][3])])
                    print("your card:", card, "your stack:", new_state[2][0]/ether, "opp stack:", new_state[2][1]/ether)
                else:
                    card = self.dealer.reveal_card(self.current_deck[1], [self.dealer.get_card_key(1), ECPrivateKey(alpha=new_state[3][6])])
                    print("your card:", card, "your stack:", new_state[2][1]/ether, "opp stack:", new_state[2][0]/ether)
                print("pot:", new_state[2][2]/ether, "to call:", new_state[2][3]/ether)
                continue_ = False
                i = 0
                while not continue_:
                    i += 1
                    action_type = input("[fold=0, call=1, raise=2]:")
                    if i > 8:
                        raise ValueError("too many mistakes")
                    if action_type=="0":
                        new_state[1][1] = 0
                        new_state[2][3] = 0
                        new_encoded = self.poker_contract.encode_state(*new_state)
                        valid = self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in)
                        if valid:
                            continue_ = True
                        else:
                            print("invalid state transition??")
                    elif action_type=="1":
                        to_call = new_state[2][3]
                        new_state[1][1] = 1
                        new_state[2][3] = 0
                        new_state[2][2] += to_call
                        if self.players[0]==self.account.address:
                            new_state[2][0] -= to_call
                        else:
                            new_state[2][1] -= to_call
                        new_encoded = self.poker_contract.encode_state(*new_state)
                        valid = self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in)
                        if valid:
                            continue_ = True
                        else:
                            print("invalid state transition??")
                    elif action_type=="2":
                        raise_str = input(f"call {new_state[2][3]/ether} and raise ({(self.buy_in//50)/ether} min):")
                        try:
                            raise_amnt = Web3.toWei(float(raise_str), 'ether')
                            total_bet = raise_amnt + new_state[2][3]
                            if ((raise_amnt >= self.buy_in//50) or (total_bet==new_state[2][0]) or (total_bet==new_state[2][1])) and (((total_bet<=new_state[2][0]) and (self.players[0] == self.account.address)) or ((total_bet<=new_state[2][1]) and (self.players[1] == self.account.address))):
                                if (self.account.address == self.players[0]) and (raise_amnt > new_state[2][1]):
                                    raise_amnt = new_state[2][1]
                                    total_bet = raise_amnt + new_state[2][3]
                                elif (self.account.address == self.players[1]) and (raise_amnt > new_state[2][0]):
                                    raise_amnt = new_state[2][0]
                                    total_bet = raise_amnt + new_state[2][3]
                                new_state[1][1] = 2
                                new_state[2][2] += total_bet
                                new_state[2][3] = raise_amnt
                            else:
                                raise ValueError("")
                            if self.players[0]==self.account.address:
                                new_state[2][0] -= total_bet
                            else:
                                new_state[2][1] -= total_bet
                            new_encoded = self.poker_contract.encode_state(*new_state)
                            valid = self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in)
                            if valid:
                                continue_ = True
                            else:
                                print("invalid state transition??")
                        except:
                            print("invalid raise amount entered")
                    else:
                        print("bad input try again!")
                my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                idx = 0
                while not self.table_contract.verify_half_signed_tx(new_encoded, my_new_sig, self.account.address):
                    idx += 1
                    my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                    if idx > 10:
                        raise ValueError("created invalid signature on state transition")
                hand_msg = json.dumps({'msgtype':'hand', 'type': 1, 'previous_state': binascii.hexlify(current_encoded).decode(), 'next_state': binascii.hexlify(new_encoded).decode(), 'next_v': my_new_sig[0], 'next_r': my_new_sig[1], 'next_s': my_new_sig[2], 'prev_v': my_sig[0], 'prev_r': my_sig[1], 'prev_s': my_sig[2]})
                hand_msg = hand_msg + "\n"
                self.current_state = new_state
                self.current_state_sigs = {self.account.address: my_new_sig}
                self.transport.write(str.encode(hand_msg))
            elif self.current_state[1][1] == 0:
                new_state[4][1] = self.account.address
                if self.players[0]==self.account.address:
                    new_state[2][0] += new_state[2][2]
                else:
                    new_state[2][1] += new_state[2][2]
                new_state[2][2] = 0
                new_state[2][3] = 0
                new_state[1][1] = 4
                new_encoded = self.poker_contract.encode_state(*new_state)
                if not self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in):
                    raise ValueError(f"invalid new state created here: {self.current_state[1][1]}")
                my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                idx = 0
                while not self.table_contract.verify_half_signed_tx(new_encoded, my_new_sig, self.account.address):
                    idx += 1
                    my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                    if idx > 10:
                        raise ValueError("created invalid signature on state transition")
                hand_msg = json.dumps({'msgtype':'hand', 'type': 2, 'previous_state': binascii.hexlify(current_encoded).decode(), 'next_state': binascii.hexlify(new_encoded).decode(), 'next_v': my_new_sig[0], 'next_r': my_new_sig[1], 'next_s': my_new_sig[2], 'prev_v': my_sig[0], 'prev_r': my_sig[1], 'prev_s': my_sig[2]})
                hand_msg = hand_msg + "\n"
                self.current_state = new_state
                self.current_state_sigs = {self.account.address: my_new_sig}
                self.transport.write(str.encode(hand_msg))
            elif self.current_state[1][1] == 1:
                if self.players[0]==self.account.address:
                    new_state[3][2] = self.dealer.get_card_key(0).alpha
                else:
                    new_state[3][7] = self.dealer.get_card_key(1).alpha
                new_state[1][1] = 3
                new_encoded = self.poker_contract.encode_state(*new_state)
                if not self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in):
                    raise ValueError(f"invalid new state created here: {self.current_state[1][1]}")
                my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                idx = 0
                while not self.table_contract.verify_half_signed_tx(new_encoded, my_new_sig, self.account.address):
                    idx += 1
                    my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                    if idx > 10:
                        raise ValueError("created invalid signature on state transition")
                hand_msg = json.dumps({'msgtype':'hand', 'type': 1, 'previous_state': binascii.hexlify(current_encoded).decode(), 'next_state': binascii.hexlify(new_encoded).decode(), 'next_v': my_new_sig[0], 'next_r': my_new_sig[1], 'next_s': my_new_sig[2], 'prev_v': my_sig[0], 'prev_r': my_sig[1], 'prev_s': my_sig[2]})
                hand_msg = hand_msg + "\n"
                self.current_state = new_state
                self.current_state_sigs = {self.account.address: my_new_sig}
                self.transport.write(str.encode(hand_msg))
            elif self.current_state[1][1] == 3:
                if self.players[0]==self.account.address:
                    new_state[3][2] = self.dealer.get_card_key(0).alpha
                    card1 = self.dealer.reveal_card(self.current_deck[0], [ECPrivateKey(alpha=new_state[3][2]), ECPrivateKey(alpha=new_state[3][3])])
                    card2 = self.dealer.reveal_card(self.current_deck[1], [ECPrivateKey(alpha=new_state[3][6]), ECPrivateKey(alpha=new_state[3][7])])
                    print(f"your card: {card1} opp card: {card2}")
                else:
                    new_state[3][7] = self.dealer.get_card_key(1).alpha
                    card1 = self.dealer.reveal_card(self.current_deck[0], [ECPrivateKey(alpha=new_state[3][2]), ECPrivateKey(alpha=new_state[3][3])])
                    card2 = self.dealer.reveal_card(self.current_deck[1], [ECPrivateKey(alpha=new_state[3][6]), ECPrivateKey(alpha=new_state[3][7])])
                    print(f"your card: {card2} opp card: {card1}")
                try:
                    if cards.index(card1) < cards.index(card2):
                        if self.players[0]==self.account.address:
                            print(f"high card: {card2}, you lost.")
                        else:
                            print(f"high card: {card2}, you won.")
                    else:
                        if self.players[0]==self.account.address:
                            print(f"high card: {card1}, you won.")
                        else:
                            print(f"high card: {card1}, you lost.")
                except:
                    pass
                input("press enter (to reveal)")
                new_state[1][1] = 3
                new_encoded = self.poker_contract.encode_state(*new_state)
                if not self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in):
                    raise ValueError(f"invalid new state created here: {self.current_state[1][1]}")
                my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                idx = 0
                while not self.table_contract.verify_half_signed_tx(new_encoded, my_new_sig, self.account.address):
                    idx += 1
                    my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                    if idx > 10:
                        raise ValueError("created invalid signature on state transition")
                hand_msg = json.dumps({'msgtype':'hand', 'type': 2, 'previous_state': binascii.hexlify(current_encoded).decode(), 'next_state': binascii.hexlify(new_encoded).decode(), 'next_v': my_new_sig[0], 'next_r': my_new_sig[1], 'next_s': my_new_sig[2], 'prev_v': my_sig[0], 'prev_r': my_sig[1], 'prev_s': my_sig[2]})
                hand_msg = hand_msg + "\n"
                self.current_state = new_state
                self.current_state_sigs = {self.account.address: my_new_sig}
                self.transport.write(str.encode(hand_msg))
            else:
                raise ValueError("Hand message round 2 is not properly formatted")
        if hand["type"] == 2:
            if self.current_state[1][1] == 3:
                new_state[1][1] = 4
                card1 = self.dealer.reveal_card(self.current_deck[0], [ECPrivateKey(alpha=self.current_state[3][2]), ECPrivateKey(alpha=self.current_state[3][3])])
                card2 = self.dealer.reveal_card(self.current_deck[1], [ECPrivateKey(alpha=self.current_state[3][6]), ECPrivateKey(alpha=self.current_state[3][7])])
                if self.players[0]==self.account.address:
                    print(f"your card: {card1} opp card: {card2}")
                else:
                    print(f"your card: {card2} opp card: {card1}")
                try:
                    if cards.index(card1) < cards.index(card2):
                        new_state[4][1] = self.players[1]
                        new_state[2][1] += new_state[2][2]
                        new_state[2][2] = 0
                        new_state[2][3] = 0
                        if self.players[0]==self.account.address:
                            print(f"high card: {card2}, you lost.")
                        else:
                            print(f"high card: {card2}, you won.")
                    else:
                        new_state[4][1] = self.players[0]
                        new_state[2][0] += new_state[2][2]
                        new_state[2][2] = 0
                        new_state[2][3] = 0
                        if self.players[0]==self.account.address:
                            print(f"high card: {card1}, you won.")
                        else:
                            print(f"high card: {card1}, you lost.")
                except:
                    pass
                input("press enter (to continue)")
                new_encoded = self.poker_contract.encode_state(*new_state)
                if not self.poker_contract.is_valid_transition(current_encoded, new_encoded, self.players, self.buy_in):
                    print("last state:", self.current_state)
                    print("new state:", new_state)
                    raise ValueError(f"invalid new state created here: {self.current_state[1][1]}")
                my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                idx = 0
                while not self.table_contract.verify_half_signed_tx(new_encoded, my_new_sig, self.account.address):
                    idx += 1
                    my_new_sig = self.table_contract.sign_table_tx(new_encoded)
                    if idx > 10:
                        raise ValueError("created invalid signature on state transition")
                hand_msg = json.dumps({'msgtype':'hand', 'type': 2, 'previous_state': binascii.hexlify(current_encoded).decode(), 'next_state': binascii.hexlify(new_encoded).decode(), 'next_v': my_new_sig[0], 'next_r': my_new_sig[1], 'next_s': my_new_sig[2], 'prev_v': my_sig[0], 'prev_r': my_sig[1], 'prev_s': my_sig[2]})
                hand_msg = hand_msg + "\n"
                self.current_state = new_state
                self.current_state_sigs = {self.account.address: my_new_sig}
                self.transport.write(str.encode(hand_msg))
            elif self.current_state[1][1] == 4:
                i = 0
                continue_ = False
                while not continue_:
                    i += 1
                    action_type = None
                    wait = True
                    if (self.current_state[2][0] == 0) or (self.current_state[2][1] == 0):
                        print("game over")
                        if ((self.players[0] == self.account.address) and (self.current_state[2][0] == 0)) or ((self.players[1] == self.account.address) and (self.current_state[2][1] == 0)):
                            print("you lost")
                        else:
                            print("you won!")
                        action_type = "2"
                        wait = False
                    else:                     
                        action_type = input("[continue playing=1, cash out=2]:")
                    if i > 8:
                        raise ValueError("too many mistakes")
                    if action_type == "1":
                        hand_msg = json.dumps({'msgtype':'handover', 'previous_state': hand['next_state'], 'prev_v': my_sig[0], 'prev_r': my_sig[1], 'prev_s': my_sig[2], "stop": 0, "tx": ""})
                        hand_msg = hand_msg + "\n"
                        continue_ = True
                        self.transport.write(str.encode(hand_msg))                        
                    elif action_type == "2":
                        try:
                            signed_state = self.signed_states[-1]
                            tx = self.table_contract.propose_settlement(signed_state["signatures"], binascii.unhexlify(signed_state["state"]), 2*self.default_gas)
                            print(f"proposed settlement. Tx here: {binascii.hexlify(tx)}")
                            hand_msg = json.dumps({'msgtype':'handover', 'previous_state': hand['next_state'], 'prev_v': my_sig[0], 'prev_r': my_sig[1], 'prev_s': my_sig[2], 'stop': 1, 'tx': binascii.hexlify(tx).decode()})
                            hand_msg = hand_msg + "\n"
                            if wait == True:
                                print(f"{self.dispute_duration} seconds before money can be remitted... RUN THIS: python3 settlement.py {binascii.hexlify(self.table_contract.sessionID).decode()}.pkr <infura url> <private key>")
                            else:
                                print(f"eth should be cashed out!")
                            continue_ = True
                            self.transport.write(str.encode(hand_msg))
                        except:
                            print(f"RUN THIS: python3 settlement.py {binascii.hexlify(self.table_contract.sessionID).decode()}.pkr <infura url> <private key>")
                            return            
                    else:
                        print("invalid input try again.")

    def handover(self, hand):
        hand = json.loads(hand.decode('utf-8'))
        player = self.players[0] if self.players[1]==self.account.address else self.players[1]
        prev_encoded = binascii.unhexlify(hand['previous_state'])
        current_encoded = self.poker_contract.encode_state(*self.current_state)
        if prev_encoded != current_encoded:
            print(decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], current_encoded))
            print(decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], prev_encoded))
            raise ValueError("received invalid state")
        sig = [hand["prev_v"], hand["prev_r"], hand["prev_s"]]      
        if not self.table_contract.verify_half_signed_tx(prev_encoded, sig, player):
            raise ValueError("received invalid signature on state")
        self.current_state_sigs[self.remote_address] = sig
        if len(self.current_state_sigs) != 2:
            raise ValueError("Missing own signature on previous state somehow")
        self.signed_states.append({'state': binascii.hexlify(current_encoded).decode(), 'signatures': self.current_state_sigs})
        game = json.dumps({'game': self.game_basics, 'states': self.signed_states, 'unfinished': ''})
        with open(self.backup_file, "w") as f:
            f.write(game)
        if hand["stop"] == 1:
            print(f"print opponent {self.remote_address} ended the game.")
            print(f"see here: {hand['tx']}")
            if (self.current_state[2][0] == 0) or (self.current_state[2][1] == 0):
                print("eth should be cashed out.")
            else:
                print(f"{self.dispute_duration} seconds before money will be remitted... either wait without quitting or RUN THIS: python3 settlement.py {binascii.hexlify(self.table_contract.sessionID).decode()}.pkr <infura url> <private key>")
                time.sleep(self.dispute_duration+120)
                tx = self.table_contract.claim_expired_settlement(self.table_contract.tableID, self.default_gas)
                print("eth should now be cashed out:", binascii.hexlify(tx))
            return            
        else:         
            i = 0
            continue_ = False
            while not continue_:
                i += 1
                action_type = None
                wait = False
                if self.current_state[2][0] == 0 or self.current_state[2][1] == 0:
                    print("game over")
                    if ((self.players[0] == self.account.address) and (self.current_state[2][0] == 0)) or ((self.players[1] == self.account.address) and (self.current_state[2][1] == 0)):
                        print("you lost")
                    else:
                        print("you won!")
                    wait = True
                    return
                else:                     
                    action_type = input("[continue playing=1, cash out=2]:")
                if i > 8:
                    raise ValueError("too many mistakes")
                if action_type == "1":
                    continue_ = True
                    return self.start_shuffle()                  
                elif action_type == "2":
                    try:
                        signed_state = self.signed_states[-1]
                        tx = self.table_contract.propose_settlement(signed_state["signatures"], binascii.unhexlify(signed_state["state"]), 2*self.default_gas)
                        print(f"proposed settlement. Tx here: {binascii.hexlify(tx)}")
                        continue_ = True
                        hand_msg = json.dumps({'msgtype':'handover', 'previous_state': signed_state["state"], 'prev_v': my_sig[0], 'prev_r': my_sig[1], 'prev_s': my_sig[2], "stop": 1, 'tx': binascii.hexlify(tx).decode()})
                        hand_msg = hand_msg + "\n"
                        if wait == True:
                            print(f"{self.dispute_duration} seconds before money can be remitted... RUN THIS: python3 settlement.py {binascii.hexlify(self.table_contract.sessionID).decode()}.pkr <infura url> <private key>")
                        else:
                            print(f"eth should be cashed out!")
                        self.transport.write(str.encode(hand_msg))
                    except:
                        print(f"RUN THIS: python3 settlement.py {binascii.hexlify(self.table_contract.sessionID).decode()}.pkr <infura url> <private key>")
                        return      
                else:
                    print("invalid input try again.")


class PlayerFactory(Factory):

    protocol = Player

    def __init__(self, priv, w3, randomness, buy_in, duration, join_duration, dispute_duration):
        self.priv = priv
        self.w3 = w3
        self.randomness = randomness
        self.buy_in = buy_in
        self.duration = duration
        self.join_duration = join_duration
        self.dispute_duration = dispute_duration

    def buildProtocol(self, *args, **kwargs):
        protocol = Player(self.priv, self.w3, self.randomness, self.buy_in, self.duration, self.join_duration, self.dispute_duration, False)
        return protocol
