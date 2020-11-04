pragma solidity 0.5.0;

contract HighCardGameState {
    function isValidStateTransition(bytes memory, bytes memory, address payable[2] memory, uint256) public view returns (bool) {}
    function isValidStateFastForward(bytes memory, bytes memory, address payable[2] memory, uint256) public view returns (bool) {}
    function getPot(bytes memory) public pure returns (uint256) {}
    function getActionType(bytes memory) public pure returns (uint8) {}
    function getBalances(bytes memory) public pure returns (uint256[2] memory) {}
    function initialEncodedState(uint256) public view returns (bytes memory) {}
}

contract HeadsUpTables {
    // Precomputed hashes for EIP712 domain separator (unique identifier for messages pertaining to this contract)
    bytes32 constant EIP712DOMAINTYPE_HASH = 0x0eaa6c88c44fbde2113ba7421deef795c18fc5a553a55b2ba4d237269e1c2662;
    bytes32 constant NAME_HASH = 0x27a59e84af55de2071cfadf11be6f3ca6437c9e6d2bf408c02566f4d13d28d8a;
    bytes32 constant VERSION_HASH = 0xc89efdaa54c0f20c7adf612882df0950f5a951637e0307cdcb4c672f298b8bc6;
    bytes32 constant SALT = 0xb1ae92db93da5bd8411028f6531126984a6eb2e7f66b19e5c22d5a7b0fb00bc7;
    
    // Domain separator completed on contract construction
    bytes32 public DOMAIN_SEPARATOR;
    
    // Dispute types
    uint8 constant public noDispute = 0;
    uint8 constant public unresponsiveDispute = 1;
    uint8 constant public malformedDispute = 2;
    
    // Action types
    uint8 constant public foldAction = 0;
    uint8 constant public callAction = 1;
    uint8 constant public raiseAction = 2;
    uint8 constant public revealAction = 3;
    uint8 constant public commitAction = 4;
    
    // Structs
    struct State {
        uint256[2] currentBalances;
        bytes encodedState;
    }
    struct Claim {
        uint8 disputeType;
        bytes disputeData;
        address proposer;
        uint256 redeemTime;
    }
    struct Table {
        bytes32 tableID; // Deterministic ID for any 2 players (same 2 addresses can only play one table at a time)
        bytes32 sessionID; // Uniqueness in case same addresses play multiple times
        address payable[2] participants;
        uint256 buyIn;
        uint256 fee;
        uint256 smallBlind;
        uint256 tableExpiration;
        uint256 joinExpiration;
        State state;
        Claim Claim;
        bool inClaim;
        bool isJoined;
        uint256 disputeDuration;    
    }
    HighCardGameState poker;
    uint256 public latestTableExpiration;
    address payable public owner;
    mapping (bytes32 => Table) tables;
    mapping (bytes32 => bool) public activeTable;
    bytes32[] public activeTables;
    // Flat one time fee to play at a table set at 1% (no rake)
    uint8 constant public feePercentage = 1;

    /// PUBLIC STATE MODIFYING FUNCTIONS
    constructor (address pokerGameAddress, uint256 contractMaxDuration, uint8 chainID) public {
        DOMAIN_SEPARATOR = keccak256(abi.encode(EIP712DOMAINTYPE_HASH, NAME_HASH, VERSION_HASH, chainID, this, SALT));
        latestTableExpiration = now+contractMaxDuration;
        poker = HighCardGameState(pokerGameAddress);
        owner = msg.sender;
    }
    
    function openTable(address payable[2] memory participants, bytes memory openData, uint8[2] memory vs, bytes32[2] memory rs, bytes32[2] memory ss, bytes32 uniqueSessionID) public payable {
        require(participants[0] == msg.sender || participants[1] == msg.sender);
        bytes32 tableID = getTableID(participants[0], participants[1]);
        bytes32 hash = getTableTransactionHash(tableID, uniqueSessionID, openData);
        require(ecrecover(hash, vs[0], rs[0], ss[0]) == participants[0]);
        require(ecrecover(hash, vs[1], rs[1], ss[1]) == participants[1]);
        require(tables[tableID].tableID != tableID);
        require(!activeTable[tableID]);
        require(msg.value>=1000 && msg.value%100==0);
        uint256 feeReceived = (msg.value*feePercentage)/100;
        uint256 buyInReceived = msg.value - feeReceived;
        (uint256 buyIn, uint256 fee, uint256 tableDuration, uint256 joinDuration, uint256 disputeDuration) = abi.decode(openData, (uint256, uint256, uint256, uint256, uint256));
        // Optional (but recommended): require duration minimums
        //require(tableDuration >= 600 && disputeDuration >= 600)
        require(now+tableDuration+disputeDuration < latestTableExpiration);
        require(joinDuration<tableDuration);
        require(buyIn+fee == buyInReceived+feeReceived);
        require(buyIn%100==0);
        tables[tableID].tableExpiration = now+tableDuration;
        tables[tableID].joinExpiration = now+joinDuration;
        tables[tableID].disputeDuration = disputeDuration;
        tables[tableID].tableID = tableID;
        tables[tableID].sessionID = uniqueSessionID;
        tables[tableID].participants[0] = participants[0];
        tables[tableID].participants[1] = participants[1];
        tables[tableID].buyIn = buyIn;
        tables[tableID].fee = fee;
        tables[tableID].smallBlind = buyIn/100;
        if (participants[0] == msg.sender) {
            tables[tableID].state.currentBalances[0] = buyIn;
        } else {
            tables[tableID].state.currentBalances[1] = buyIn;
        }
        activeTable[tableID] = true;
        activeTables.push(tableID); 
    }
    
    function joinTable(address payable[2] memory participants) public payable {
        bytes32 tableID = getTableID(participants[0], participants[1]);
        require(activeTable[tableID]);
        require(tables[tableID].tableID == tableID);
        require(!tables[tableID].isJoined);
        require(now < tables[tableID].joinExpiration);
        require(tables[tableID].buyIn+tables[tableID].fee == msg.value);
        require(tables[tableID].participants[0] == msg.sender || tables[tableID].participants[1] == msg.sender);
        if (tables[tableID].participants[0] == msg.sender) {
            require(tables[tableID].state.currentBalances[0] == 0);
            tables[tableID].state.currentBalances[0] = tables[tableID].buyIn;
        } else {
            require(tables[tableID].state.currentBalances[1] == 0);
            tables[tableID].state.currentBalances[1] = tables[tableID].buyIn;            
        }
        tables[tableID].state.encodedState = poker.initialEncodedState(tables[tableID].smallBlind);
        tables[tableID].isJoined = true;
    }
    
    function proposeClaim(bytes32 tableID, bytes memory ClaimData, uint8 v, bytes32 r, bytes32 s) public {
        require(activeTable[tableID]);
        require(tables[tableID].isJoined);
        if (!tables[tableID].inClaim) {
            // Must propose a Claim before table expires if no settlment already exists.
            require(now < tables[tableID].tableExpiration);
        } else {
            // If Claim already exists can propose a challenge up until the end of existing Claim dispute period.
            // To avoid infinite Claim loops no Claim can be proposed after latestTableExpiration.
            require(now < tables[tableID].Claim.redeemTime && now < latestTableExpiration);
        }
        
        // Verify and unpack Claim data
        (bytes memory finalStateData, address proposer, uint8 disputeType, bytes memory disputeData) = verifyUnpackClaimData(tableID, ClaimData, v, r, s);
        
        // Verify and unpack final state data
        bytes memory encodedNewState = verifySignedStateData(tableID, finalStateData);
        
        // Handle Claim
        handleClaim(tableID, encodedNewState, proposer, disputeType, disputeData);
    }
    
    function claimExpiredTable(bytes32 tableID) public {
        require(activeTable[tableID]);
        require(!tables[tableID].inClaim);
        if (tables[tableID].isJoined) {
            if (now > tables[tableID].tableExpiration) {
                closeTable(tableID);
            }
        } else {
            if (now > tables[tableID].joinExpiration) {
                closeTable(tableID);
            }
        }
    }
    
    function claimExpiredClaim(bytes32 tableID) public {
        require(activeTable[tableID]);
        require(tables[tableID].inClaim);
        require(now > tables[tableID].Claim.redeemTime);
        require(tables[tableID].Claim.proposer == tables[tableID].participants[0] || tables[tableID].Claim.proposer == tables[tableID].participants[1]);
        if (tables[tableID].Claim.proposer == tables[tableID].participants[0]) {
            tables[tableID].state.currentBalances[0] += poker.getPot(tables[tableID].state.encodedState);
        } else {
            tables[tableID].state.currentBalances[1] += poker.getPot(tables[tableID].state.encodedState);
        }
        closeTable(tableID);
    }
    
    function claimContract() public {
        // Only owner can destroy contract
        require(msg.sender == owner);
        // Contract can only be destroyed when there are no active tables (all players have cashed out).
        require(activeTables.length == 0);
        selfdestruct(owner);
    }
    
    function transferOwnership(address payable newOwner) public {
        require(msg.sender==owner);
        owner = newOwner;
    }
    
    /// INTERNAL (PROTECTED) STATE MODIFYING FUNCTIONS
    function advanceToVerifiedState(bytes32 tableID, bytes memory encodedState) internal {
        tables[tableID].state.encodedState = encodedState;
        tables[tableID].state.currentBalances = poker.getBalances(encodedState);
    }
    
    function handleClaim(bytes32 tableID, bytes memory encodedNewState, address proposer, uint8 disputeType, bytes memory disputeData) internal {
        require(poker.isValidStateFastForward(tables[tableID].state.encodedState, encodedNewState, tables[tableID].participants, tables[tableID].smallBlind));
        advanceToVerifiedState(tableID, encodedNewState);
        if (disputeType==noDispute && poker.getActionType(tables[tableID].state.encodedState)!=commitAction) {
            require(false);
        } else if (disputeType==noDispute && poker.getActionType(tables[tableID].state.encodedState)==commitAction && (tables[tableID].state.currentBalances[0]==0 || tables[tableID].state.currentBalances[1]==0)) {
            closeTable(tableID);
        } else if (disputeType==noDispute || (disputeType == unresponsiveDispute && verifyUnresponsiveDispute(tableID, disputeData, proposer))) { 
            tables[tableID].inClaim = true;
            uint256 redeemTime = now+tables[tableID].disputeDuration;
            tables[tableID].Claim = Claim({proposer: proposer, disputeType: disputeType, disputeData: disputeData, redeemTime: redeemTime});              
        } else if (disputeType==malformedDispute && verifyMalformedDispute(tableID, disputeData, proposer)) {
            if (proposer == tables[tableID].participants[0]) {
                tables[tableID].state.currentBalances[0] += poker.getPot(tables[tableID].state.encodedState);
            } else if (proposer == tables[tableID].participants[1]) {
                tables[tableID].state.currentBalances[1] += poker.getPot(tables[tableID].state.encodedState);
            } else {
                require(false);
            }
            closeTable(tableID);
        } else {
            require(false);
        }
    }
    
    function closeTable(bytes32 tableID) internal {
        uint256 amount1 = tables[tableID].state.currentBalances[0];
        uint256 amount2 = tables[tableID].state.currentBalances[1];
        address payable p1 = tables[tableID].participants[0];
        address payable p2 = tables[tableID].participants[1];
        if (tables[tableID].isJoined) {
            require(amount1+amount2 == 2*tables[tableID].buyIn);
        } else {
            require(amount1+amount2 == tables[tableID].buyIn);
        }
        delete tables[tableID];
        delete activeTable[tableID];
        for (uint256 i=0; i<activeTables.length; i++) {
            if (activeTables[i] == tableID) {
                activeTables[i] = activeTables[activeTables.length-1];
                delete activeTables[activeTables.length-1];
                activeTables.length--;
            }
        }
        p1.transfer(amount1);
        p2.transfer(amount2);
    }
    
    /// PUBLIC VIEW/PURE FUNCTIONS
    function getTableID(address participant1, address participant2) public view returns (bytes32) {
        require(participant1<participant2);
        return keccak256(abi.encodePacked(DOMAIN_SEPARATOR, participant1, participant2));
    }
    
    function getTableTransactionHash(bytes32 tableID, bytes32 sessionID, bytes memory txData) public pure returns (bytes32) {
        return prefixedHash(tableID, sessionID, keccak256(txData));
    }
    
    function getTableOverview(bytes32 tableID) public view returns (address payable[2] memory, uint256[5] memory, bool[2] memory) {
        require(activeTable[tableID]);
        uint256[5] memory nums;
        nums[0] = tables[tableID].buyIn;
        nums[1] = tables[tableID].fee;
        nums[2] = tables[tableID].tableExpiration;
        nums[3] = tables[tableID].joinExpiration;
        nums[4] = tables[tableID].disputeDuration;
        bool[2] memory bools;
        bools[0] = tables[tableID].isJoined;
        bools[1] = tables[tableID].inClaim;
        return (tables[tableID].participants, nums, bools);
    }
    
    function getTableClaim(bytes32 tableID) public view returns (uint8, address, uint256, bytes memory) {
        require(activeTable[tableID]);
        require(tables[tableID].inClaim);
        return (tables[tableID].Claim.disputeType, tables[tableID].Claim.proposer, tables[tableID].Claim.redeemTime, tables[tableID].Claim.disputeData);
    }
    
    function getTableState(bytes32 tableID) public view returns (bytes memory) {
        require(activeTable[tableID]);
        return tables[tableID].state.encodedState;
    }
    
    function verifySignedStateData(bytes32 tableID, bytes memory stateData) public view returns (bytes memory) {
        (bytes memory encodedState, uint8[2] memory vs, bytes32[2] memory rs, bytes32[2] memory ss) = abi.decode(stateData, (bytes, uint8[2], bytes32[2], bytes32[2]));
        bytes32 hash = getOpenTableTransactionHash(tableID, encodedState);
        require(ecrecover(hash, vs[0], rs[0], ss[0]) == tables[tableID].participants[0]);
        require(ecrecover(hash, vs[1], rs[1], ss[1]) == tables[tableID].participants[1]);
        
        return encodedState;
    }
    
    function verifyHalfSignedStateData(bytes32 tableID, bytes memory stateData, address signer) public view returns (bytes memory) {
        (bytes memory encodedState, uint8 v, bytes32 r, bytes32 s) = abi.decode(stateData, (bytes, uint8, bytes32, bytes32));
        bytes32 hash = getOpenTableTransactionHash(tableID, encodedState);
        require(ecrecover(hash, v, r, s) == signer);
        return encodedState;
    }
    
    function verifyUnpackClaimData(bytes32 tableID, bytes memory ClaimData, uint8 v, bytes32 r, bytes32 s) public view returns (bytes memory, address, uint8, bytes memory) {
        (bytes memory finalStateData, address proposer, uint8 disputeType, bytes memory disputeData) = abi.decode(ClaimData, (bytes, address, uint8, bytes));
        require(proposer==tables[tableID].participants[0] || proposer==tables[tableID].participants[1]);
        bytes32 hash = getOpenTableTransactionHash(tableID, ClaimData);
        require(ecrecover(hash, v, r, s)==proposer);
        
        return (finalStateData, proposer, disputeType, disputeData);
    }

    function verifyUnresponsiveDispute(bytes32 tableID, bytes memory disputeData, address proposer) public view returns (bool) {
        bytes memory encodedNewState = verifyHalfSignedStateData(tableID, disputeData, proposer);
        return poker.isValidStateTransition(tables[tableID].state.encodedState, encodedNewState, tables[tableID].participants, tables[tableID].smallBlind);
    }
    
    function verifyMalformedDispute(bytes32 tableID, bytes memory disputeData, address proposer) public view returns (bool) {
        address signer = tables[tableID].participants[0];
        if (proposer == tables[tableID].participants[0]) {
            signer = tables[tableID].participants[1];
        }
        bytes memory encodedNewState = verifyHalfSignedStateData(tableID, disputeData, signer);
        return !poker.isValidStateTransition(tables[tableID].state.encodedState, encodedNewState, tables[tableID].participants, tables[tableID].smallBlind);
    }
    
    /// INTERNAL VIEW/PURE FUNCTIONS
    function getOpenTableTransactionHash(bytes32 tableID, bytes memory txData) internal view returns (bytes32) {
        return prefixedHash(tableID, tables[tableID].sessionID, keccak256(txData));
    }
    function prefixedHash(bytes32 tableID, bytes32 sessionID, bytes32 txHash) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked("\x19\x01", tableID, sessionID, txHash));
    }
}