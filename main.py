import asyncio
import json
import time

from indy import pool, wallet, did, ledger, anoncreds
from indy.error import ErrorCode, IndyError

async def create_wallet(identity):
    print("\"{}\" -> Create Wallet".format(identity['name']))
    try:
        await wallet.create_wallet(identity['wallet_config'], identity['wallet_credentials'])
    except IndyError as ex:
        if ex.error_code == ErrorCode.PoolLedgerConfigAlreadyExistsError:
            pass
    identity['wallet'] = await wallet.open_wallet(identity['wallet_config'], identity['wallet_credentials'])
    
async def getting_verinym(from_, to):
    await create_wallet(to)
    
    (to['did'], to['key']) = await did.create_and_store_my_did(to['wallet'], "{}")
    
    from_['info'] = {
        'did': to['did'],
        'verkey': to['key'],
        'role': to['role'] or None
    }
    
    await send_nym(from_['pool'], from_['wallet'], from_['did'], from_['info']['did'], from_['info']['verkey'], from_['info']['role'])
    
async def send_nym(pool_handle, wallet_handle, _did, new_did, new_key, role ):
    nym_request = await ledger.build_nym_request(_did, new_did, new_key, None, role)
    print(nym_request)
    await ledger.sign_and_submit_request(pool_handle, wallet_handle, _did, nym_request)

async def ensure_previous_request_applied(pool_handle, checker_request, checker):
    for _ in range(3):
        response = json.loads(await ledger.submit_request(pool_handle, checker_request))
        try:
            if checker(response):
                return json.dumps(response)
        except TypeError:
            pass
        time.sleep(5)

async def get_cred_def(pool_handle, _did, cred_def_id):
    get_cred_def_request = await ledger.build_get_cred_def_request(_did, cred_def_id)
    get_cred_def_response = await ensure_previous_request_applied(pool_handle, get_cred_def_request, lambda response: response['result']['data'] is not None)
    return await ledger.parse_get_cred_def_response(get_cred_def_response)

# MAIN CODE

async def run():
    print("Indy demo program")

    print("\n-------------------------")
    print("STEP 1: Connect to pool")
    print("-------------------------")

    pool_config = {
        "name": "pool1",
        "genesis_txn_path": "pool1.txn",
        "config": json.dumps({"genesis_txn": "pool1.txn"})
    }

    # connect to pool
    await pool.set_protocol_version(2)
    try:
        await pool.create_pool_ledger_config(pool_config['name'], pool_config['config'])
    except IndyError as ex:
        if ex.error_code == ErrorCode.PoolLedgerConfigAlreadyExistsError:
            pass
    pool_handle = await pool.open_pool_ledger(pool_config['name'], None)

    print(pool_handle)
    
    print("\n-------------------------")
    print("STEP 2: Configuring steward")
    print("-------------------------")

    steward = {
        'name': "Sovrin steward",
        'wallet_config': json.dumps({ 'id': ' sovrin_steward_wallet '}),
        'wallet_credentials': json.dumps({ 'key': ' steward_wallet_key '}),
        'pool': pool_handle,
        'seed': '000000000000000000000000Steward1'
    }
    print(steward)

    await create_wallet(steward)

    print(steward['wallet'])

    steward['did_info'] = json.dumps({ 'seed': steward['seed']})
    print(steward['did_info'])

    # did:demoindynetwork: Th7MpTaRZVRYnPiabds81Y
    steward['did'], steward['key'] = await did.create_and_store_my_did(steward['wallet'], steward['did_info'])

    print("\n-------------------------")    
    print("STEP 3: Register DID for government")
    print("-------------------------")

    print("\nGovernment Getting Verinym")
    print("-------------------------")
    
    government = {
        'name': "Government",
        'wallet_config': json.dumps({ 'id': ' government_wallet '}),
        'wallet_credentials': json.dumps({ 'key': ' government_wallet_key '}),
        'pool': pool_handle,
        'role': 'TRUST_ANCHOR'
    }

    await getting_verinym(steward, government)

    print("\n-------------------------")
    print("STEP 3: Register DID for university and company")
    print("-------------------------")

    print("\nUniversity Getting Verinym")
    print("-------------------------")
    
    theUniversity = {
        'name': "theUniversity",
        'wallet_config': json.dumps({ 'id': ' theUniversity_wallet '}),
        'wallet_credentials': json.dumps({ 'key': ' theUniversity_wallet_key '}),
        'pool': pool_handle,
        'role': 'TRUST_ANCHOR'
    }

    await getting_verinym(steward, theUniversity)
    
    print("\nCompany Getting Verinym")
    print("-------------------------")
    
    theCompany = {
        'name': "theCompany",
        'wallet_config': json.dumps({ 'id': ' theCompany_wallet '}),
        'wallet_credentials': json.dumps({ 'key': ' theCompany_wallet_key '}),
        'pool': pool_handle,
        'role': 'TRUST_ANCHOR'
    }

    await getting_verinym(steward, theCompany)

    print("\n-------------------------")
    print("STEP 4: Government create credential schema")
    print("-------------------------")

    transcript = {
        'name': 'Transcript',
        'version': '1.2',
        'attributes': ['first_name', 'last_name', 'degree', 'status', 'year', 'average', 'ssn']
    }

    (government['transcript_schema_id'], government['transcript_schema']) = \
        await anoncreds.issuer_create_schema(government['did'], transcript['name'], transcript['version'], json.dumps(transcript['attributes']))

    print(government['transcript_schema'])
    transcript_schema_id = government['transcript_schema_id']

    schema_request = await ledger.build_schema_request(government['did'], government['transcript_schema'])
    await ledger.sign_and_submit_request(government['pool'], government['wallet'], government['did'], schema_request)

    print("\n-------------------------")
    print("STEP 5: University creates Transcript Credential Definition")
    print("-------------------------")

    # Get Schema from ledger
    get_schema_request = await ledger.build_get_schema_request(theUniversity['did'], transcript_schema_id)
    get_schema_response = await ensure_previous_request_applied(
        theUniversity['pool'], get_schema_request, lambda response: response['result']['data'] is not None
    )
    (theUniversity['transcript_schema_id'], theUniversity['transcript_schema']) = await ledger.parse_get_schema_response(get_schema_response)

    # Transcript credential defenition
    transcript_cred_def = {
        'tag': 'TAG1',
        'type': 'CL',   # Algorithm for signing, indy only supports this
        'config': {"support_revocation": False}
    }

    (theUniversity['transcript_cred_def_id'], theUniversity['transcript_cred_def']) = \
        await anoncreds.issuer_create_and_store_credential_def(theUniversity['wallet'], theUniversity['did'], 
                                                               theUniversity['transcript_schema'], transcript_cred_def['tag'], transcript_cred_def['type'], 
                                                               json.dumps(transcript_cred_def['config']))
    
    cred_def_request = await ledger.build_cred_def_request(theUniversity['did'], theUniversity['transcript_cred_def'])
    await ledger.sign_and_submit_request(theUniversity['pool'], theUniversity['wallet'], theUniversity['did'], cred_def_request)
    print("\n\n", theUniversity['transcript_cred_def_id'])

    print("\n-------------------------")
    print("STEP 6: University Issues Transcript Credential to Alice")
    print("-------------------------")

    # Alice requests credential from university who then gives her the requested data, in a to and fro manner

    print("\nSetting up Alice wallet")
    alice = {
        'name': "Alice",
        'wallet_config': json.dumps({'id': 'alice_wallet'}),
        'wallet_credentials': json.dumps({'key': 'alice_wallet_key'}),
        'pool': pool_handle
    }

    await create_wallet(alice)
    (alice['did'], alice['key']) = await did.create_and_store_my_did(alice['wallet'], "{}")

    print("\n University creates and sends transcript credential offer to Alice")
    theUniversity['transcript_cred_offer'] = \
        await anoncreds.issuer_create_credential_offer(theUniversity['wallet'], theUniversity['transcript_cred_def_id'])
    
    # Send the response over the network
    alice['transcript_cred_offer'] = theUniversity['transcript_cred_offer']
    print("\n Alice prepares transcript credential request")
    transcript_cred_offer_object = json.loads(alice['transcript_cred_offer'])

    alice['transcript_schema_id'] = transcript_cred_offer_object['schema_id']
    alice['transcript_cred_def_id'] = transcript_cred_offer_object['cred_def_id']

    # Alice needs a unique master secret to ensure issuer only issues one credential
    alice['master_secret_id'] = await anoncreds.prover_create_master_secret(alice['wallet'], None)

    # Credential definition from ledger
    (alice['theUniversity_transcript_cred_def_id']), alice['theUniversity_transcript_cred_def'] = \
        await get_cred_def(alice['pool'], alice['did'], alice['transcript_cred_def_id'])
    
    # Credential request for theUniversity
    (alice['transcript_cred_request'], alice['transcript_cred_request_metadata']) = \
        await anoncreds.prover_create_credential_req(alice['wallet'], alice['did'], alice['transcript_cred_offer'],
                                                     alice['theUniversity_transcript_cred_def'], alice['master_secret_id'])
    
    # Over the network to transfer message from Alice to university
    theUniversity['transcript_cred_request'] = alice['transcript_cred_request']

loop = asyncio.get_event_loop()
loop.run_until_complete(run())
