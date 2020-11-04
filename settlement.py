import os, time, json, binascii
from web3 import Web3, HTTPProvider
from contract_control import HeadsUpContract
from eth_abi import encode_abi, decode_abi
import sys

gamedir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamestate")

def run_settlement(filename, w3, priv):
	fpath = os.path.join(gamedir, filename)
	with open(fpath, "r") as f:
		data = f.read()
	gamefile = json.loads(data)
	now = time.time()
	basics = gamefile['game']
	unfinished = gamefile['unfinished']
	c = HeadsUpContract(priv, w3, contract_address="0x5fB5EDF7255e8CF168a41AD67472a76bb8304acb", players=basics['players'])
	c.sessionID = binascii.unhexlify(basics['sessionID'])
	while True:
		try:
			final_state = decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], binascii.unhexlify(gamefile['states'][-1]['state']))
			sdata = c.contract.functions.getTableSettlement(c.tableID).call()
			print("table is already in settlement")
			if sdata[1] == c.account.address:
				print("you proposed settlement")
				if time.time() > sdata[2]:
					tx = c.claim_expired_settlement(c.tableID, 3000000)
					print("cashed out:", binascii.hexlify(tx))
					return
				else:
					pass
			else:
				print("other player proposed settlement")
				s = c.contract.functions.getTableState(c.tableID).call()
				current_state = decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], s)
				if ((current_state[0] < final_state[0]) or ((current_state[0]==final_state[0]) and (current_state[1][0] < final_state[1][0]))):
					print("your final state is more up to date... updating settlement proposal")
					raise ValueError
				elif current_state[1][1] == 4:
					print("their state is valid")
					if time.time() > sdata[2]:
						tx = c.claim_expired_settlement(c.tableID, 3000000)
						print("cashed out:", binascii.hexlify(tx))
						return
					else:
						pass
				elif sdata[0] == 1:
					halfsigned = decode_abi(('bytes', 'uint8', 'bytes32', 'bytes32'), sdata[3])
					state = decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], halfsigned[0])
					print(f"continue playing where game left off (or you will have to surrender the hand with {state[2][2]/Web3.toWei(1, 'ether')} in the pot")
					return
			print()
			print("continuing to monitor the table...")
			print()
			time.sleep(10)
		except:
			try:
				if basics['start_time'] + basics['duration'] + 300 < time.time():
					print("WARNING: it is too late to cash out based on a new state (the table expired)")
					print("attemting to cash out initial buy in")
					tx = c.claim_expired_table(c.tableID, 3000000)
					print("cash out tx:", binascii.hexlify(tx))
					return
				elif basics['start_time'] + basics['duration'] < time.time():
					print("WARNING: it is very likely too late to cash out based on a new state (the table expired)")
				elif basics['start_time'] + basics['duration'] < time.time() + 300:
					print("WARNING: it is possibly too late to cash out based on a new state (if the table has expired)")
				final_state = decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], binascii.unhexlify(gamefile['states'][-1]['state']))
				tx = None
				if final_state[1][1] == 4:
					tx = c.propose_settlement(gamefile['states'][-1]["signatures"], binascii.unhexlify(gamefile['states'][-1]["state"]), 6000000)
				elif unfinished != '':
					sig = unfinished['signature']
					v = sig[0]
					r = sig[1].to_bytes((sig[1].bit_length()+7)//8, 'big')
					s = sig[2].to_bytes((sig[2].bit_length()+7)//8, 'big')
					dispute = encode_abi(('bytes', 'uint8', 'bytes32', 'bytes32'), (binascii.unhexlify(unfinished['state']), v, r, s))
					tx = c.propose_settlement(gamefile['states'][-1]["signatures"], binascii.unhexlify(gamefile['states'][-1]["state"]), 6000000, dispute_type=1, dispute_data=dispute)
				else:
					second_to_last = decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], binascii.unhexlify(gamefile['states'][-2]["state"]))
					second_to_last_sigs = gamefile['states'][-2]["signatures"]
					if final_state[-1][0] == c.account.address:
						half_state = final_state
						half_state_sig = gamefile['states'][-1]['signatures'][c.account.address]
					else:
						half_state = second_to_last
						half_state_sig = gamefile['states'][-2]['signatures'][c.account.address]
						second_to_last = decode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], binascii.unhexlify(gamefile['states'][-3]["state"]))
						second_to_last_sigs = gamefile['states'][-3]["signatures"]
					encoded = encode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], half_state)
					sig = half_state_sig
					v = sig[0]
					r = sig[1].to_bytes((sig[1].bit_length()+7)//8, 'big')
					s = sig[2].to_bytes((sig[2].bit_length()+7)//8, 'big')
					dispute = encode_abi(('bytes', 'uint8', 'bytes32', 'bytes32'), (encoded, v, r, s))
					encoded = encode_abi(['uint', 'uint8[2]','uint256[4]', 'uint256[8]', 'address[2]'], second_to_last)
					tx = c.propose_settlement(second_to_last_sigs, encoded, 6000000, dispute_type=1, dispute_data=dispute)		
				if tx == None:
					raise ValueError
				print("settlement proposed. see here:", binascii.hexlify(tx))
			except:
				print()
				print("continuing to monitor the table...")
				print()
				time.sleep(10)

if __name__ == "__main__":
	args = sys.argv[1:]
	filename = args[0]
	w3 = Web3(HTTPProvider(args[1]))
	priv = args[2]
	run_settlement(filename, w3, priv)
	os.remove(os.path.join(gamedir, filename))
	