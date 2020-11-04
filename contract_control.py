from py_eth_sig_utils import signing
from operator import itemgetter
from eth_abi import encode_abi
import sys, json, binascii

CHAIN_ID = 3 # Default Ropsten test network id.
ecsign = signing.utils.ecsign

###################
# HIGH CARD POKER #
###################

with open("abi/highcardpoker.abi", "r") as f:
	raw_poker_abi = f.read()
POKER_ABI = json.loads(raw_poker_abi)

class HighCardPokerContract:
	def __init__(self, w3_provider, contract_address=None, abi=POKER_ABI):
		self.eth = w3_provider.eth
		self.abi = abi
		if contract_address is None:
			self.contract = self.eth.contract(abi=self.abi)
		else:
			self.contract = self.eth.contract(address=contract_address, abi=abi)

	def is_valid_transition(self, last_state, new_state, players, buy_in):
		return self.contract.functions.isValidStateTransition(last_state, new_state, players, buy_in//100).call()

	def encode_state(self, hand_number, round_action, all_values, cards_keys, actor_winner):
		return encode_abi(('uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'), (hand_number, round_action, all_values, cards_keys, actor_winner))

###################
# HEADS UP TABLES #
###################

with open("abi/headsup.abi", "r") as f:
	raw_headsup_abi = f.read()
HEADSUP_ABI = json.loads(raw_headsup_abi)

class HeadsUpContract:
	def __init__(self, priv, w3_provider, contract_address=None, players=[None,None], abi=HEADSUP_ABI, chain_id=CHAIN_ID):
		self.eth = w3_provider.eth
		self.account = self.eth.account.privateKeyToAccount(priv)
		self.chain_id = chain_id
		self.abi = abi
		self.tableID = None
		self.players = players
		self.buy_in_amnt = None
		if contract_address is None:
			self.contract = self.eth.contract(abi=self.abi)
		else:
			self.contract = self.eth.contract(address=contract_address, abi=abi)
			if None not in self.players:
				self.tableID = self.contract.functions.getTableID(players[0], players[1]).call()
				res = self.contract.functions.getTableOverview(self.tableID).call()
				self.buy_in_amnt = (res[1][0]+res[1][1])//2

	def sign_new_table(self, participants, buyIn, duration, join_duration, dispute_duration, sessionID):
		fee = buyIn//100
		open_data = encode_abi(('uint256', 'uint256', 'uint256', 'uint256', 'uint256'), (buyIn, fee, duration, join_duration, dispute_duration))
		self.tableID = self.contract.functions.getTableID(participants[0], participants[1]).call()
		self.sessionID = sessionID
		txhash = self.contract.functions.getTableTransactionHash(self.tableID, self.sessionID, open_data).call()
		return ecsign(txhash, self.account.privateKey)

	def open_table_tx(self, addr2sig, participants, buyIn, duration, join_duration, dispute_duration, sessionID, gas):
		sigs = [None, None]
		for k,v in addr2sig.items():
			if k not in participants:
				raise ValueError(f"Signer {k} is not a contract owner. Remove erroneous signature.")
			if participants[0] == k:
				sigs[0] = v
			elif participants[1] == k:
				sigs[1] = v
		fee = buyIn//100
		open_data = encode_abi(('uint256', 'uint256', 'uint256', 'uint256', 'uint256'), (buyIn, fee, duration, join_duration, dispute_duration))
		v = [i[0] for i in sigs]
		r = [i[1].to_bytes((i[1].bit_length()+7)//8, 'big') for i in sigs]
		s = [i[2].to_bytes((i[2].bit_length()+7)//8, 'big') for i in sigs]		
		open_table = self.contract.functions.openTable(participants, open_data, v, r, s, sessionID)
		basetx = {"nonce": self.eth.getTransactionCount(self.account.address), "gasPrice": self.eth.gasPrice, "gas":gas, "from": self.account.address, "value": buyIn+fee}
		tx = open_table.buildTransaction(basetx)
		signed = self.account.signTransaction(tx)
		txhash = self.eth.sendRawTransaction(signed.rawTransaction)
		self.players = participants
		self.buy_in_amnt = buyIn
		self.sessionID = sessionID
		return txhash

	def join_table_tx(self, participants, buyIn, sessionID, gas):
		fee = buyIn//100
		join_table = self.contract.functions.joinTable(participants)
		basetx = {"nonce": self.eth.getTransactionCount(self.account.address), "gasPrice": self.eth.gasPrice, "gas":gas, "from": self.account.address, "value": buyIn+fee}
		tx = join_table.buildTransaction(basetx)
		signed = self.account.signTransaction(tx)
		txhash = self.eth.sendRawTransaction(signed.rawTransaction)
		self.players = participants
		self.buy_in_amnt = buyIn
		self.sessionID = sessionID
		return txhash

	def encode_state(self, hand_number, round_action, all_values, cards_keys, actor_winner):
		return encode_abi(('uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'), (hand_number, round_action, all_values, cards_keys, actor_winner))

	def sign_table_tx(self, state):
		state_hash = self.contract.functions.getTableTransactionHash(self.tableID, self.sessionID, state).call()
		return ecsign(state_hash, self.account.privateKey)

	def propose_settlement(self, addr2sig, last_state, gas, dispute_type=0, dispute_data=b''):
		sigs = [None, None]
		for k,v in addr2sig.items():
			if k not in self.players:
				raise ValueError(f"Signer {k} is not a contract owner. Remove erroneous signature.")
			if self.players[0] == k:
				sigs[0] = v
			elif self.players[1] == k:
				sigs[1] = v
		vs = [i[0] for i in sigs]
		rs = [i[1].to_bytes((i[1].bit_length()+7)//8, 'big') for i in sigs]
		ss = [i[2].to_bytes((i[2].bit_length()+7)//8, 'big') for i in sigs]
		encoded_final_state_data = encode_abi(('bytes', 'uint8[2]', 'bytes32[2]', 'bytes32[2]'), (last_state, vs, rs, ss))
		encoded_settlement = encode_abi(('bytes', 'address', 'uint8', 'bytes'), (encoded_final_state_data, self.account.address, dispute_type, dispute_data))
		settle_sig = ecsign(self.contract.functions.getTableTransactionHash(self.tableID, self.sessionID, encoded_settlement).call(), self.account.privateKey)
		settle_v, settle_r, settle_s = settle_sig[0], settle_sig[1].to_bytes((settle_sig[1].bit_length()+7)//8, 'big'), settle_sig[2].to_bytes((settle_sig[2].bit_length()+7)//8, 'big')
		proposal = self.contract.functions.proposeSettlement(self.tableID, encoded_settlement, settle_v, settle_r, settle_s)
		basetx = {"nonce": self.eth.getTransactionCount(self.account.address), "gasPrice": self.eth.gasPrice, "gas":gas, "from": self.account.address}
		tx = proposal.buildTransaction(basetx)
		signed = self.account.signTransaction(tx)
		return self.eth.sendRawTransaction(signed.rawTransaction)

	def verify_half_signed_tx(self, state, sig, signer):
		v = sig[0]
		r = sig[1].to_bytes((sig[1].bit_length()+7)//8, 'big')
		s = sig[2].to_bytes((sig[2].bit_length()+7)//8, 'big')
		encoded_verify_data = encode_abi(('bytes', 'uint8', 'bytes32', 'bytes32'), (state, v, r, s))
		try:
			self.contract.functions.verifyHalfSignedStateData(self.tableID, encoded_verify_data, signer).call()
			return True
		except:
			return False

	def claim_expired_table(self, tableID, gas):
		claim = self.contract.functions.claimExpiredTable(tableID)
		basetx = {"nonce": self.eth.getTransactionCount(self.account.address), "gasPrice": self.eth.gasPrice, "gas":gas, "from": self.account.address}
		tx = claim.buildTransaction(basetx)
		signed = self.account.signTransaction(tx)
		return self.eth.sendRawTransaction(signed.rawTransaction)

	def claim_expired_settlement(self, tableID, gas):
		claim = self.contract.functions.claimExpiredSettlement(tableID)
		basetx = {"nonce": self.eth.getTransactionCount(self.account.address), "gasPrice": self.eth.gasPrice, "gas":gas, "from": self.account.address}
		tx = claim.buildTransaction(basetx)
		signed = self.account.signTransaction(tx)
		return self.eth.sendRawTransaction(signed.rawTransaction)
