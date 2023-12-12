import asyncio
import json
import time

from indy import pool, wallet, did, ledger, anoncreds, blob_storage
from indy.error import ErrorCode, IndyError

from os.path import dirname

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

async def get_credential_for_referent(search_handle, referent):
    credentials = json.loads(
        await anoncreds.prover_fetch_credentials_for_proof_req(search_handle, referent, 10))
    return credentials[0]['cred_info']

async def prover_get_entities_from_ledger(pool_handle, _did, identifiers, actor, timestamp_from=None,
                                          timestamp_to=None):
    schemas = {}
    cred_defs = {}
    rev_states = {}
    for item in identifiers.values():
        print("\"{}\" -> Get Schema from Ledger".format(actor))
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>.", item['schema_id'])
        (received_schema_id, received_schema) = await get_schema(pool_handle, _did, item['schema_id'])
        schemas[received_schema_id] = json.loads(received_schema)

        print("\"{}\" -> Get Claim Definition from Ledger".format(actor))
        (received_cred_def_id, received_cred_def) = await get_cred_def(pool_handle, _did, item['cred_def_id'])
        cred_defs[received_cred_def_id] = json.loads(received_cred_def)

        if 'rev_reg_id' in item and item['rev_reg_id'] is not None:
            # Create Revocations States
            print("\"{}\" -> Get Revocation Registry Definition from Ledger".format(actor))
            get_revoc_reg_def_request = await ledger.build_get_revoc_reg_def_request(_did, item['rev_reg_id'])

            get_revoc_reg_def_response = \
                await ensure_previous_request_applied(pool_handle, get_revoc_reg_def_request,
                                                      lambda response: response['result']['data'] is not None)
            (rev_reg_id, revoc_reg_def_json) = await ledger.parse_get_revoc_reg_def_response(get_revoc_reg_def_response)

            print("\"{}\" -> Get Revocation Registry Delta from Ledger".format(actor))
            if not timestamp_to: timestamp_to = int(time.time())
            get_revoc_reg_delta_request = \
                await ledger.build_get_revoc_reg_delta_request(_did, item['rev_reg_id'], timestamp_from, timestamp_to)
            get_revoc_reg_delta_response = \
                await ensure_previous_request_applied(pool_handle, get_revoc_reg_delta_request,
                                                      lambda response: response['result']['data'] is not None)
            (rev_reg_id, revoc_reg_delta_json, t) = \
                await ledger.parse_get_revoc_reg_delta_response(get_revoc_reg_delta_response)

            tails_reader_config = json.dumps(
                {'base_dir': dirname(json.loads(revoc_reg_def_json)['value']['tailsLocation']),
                 'uri_pattern': ''})
            blob_storage_reader_cfg_handle = await blob_storage.open_reader('default', tails_reader_config)

            print('%s - Create Revocation State', actor)
            rev_state_json = \
                await anoncreds.create_revocation_state(blob_storage_reader_cfg_handle, revoc_reg_def_json,
                                                        revoc_reg_delta_json, t, item['cred_rev_id'])
            rev_states[rev_reg_id] = {t: json.loads(rev_state_json)}

    return json.dumps(schemas), json.dumps(cred_defs), json.dumps(rev_states)

async def get_schema(pool_handle, _did, schema_id):
    get_schema_request = await ledger.build_get_schema_request(_did, schema_id)
    get_schema_response = await ensure_previous_request_applied(
        pool_handle, get_schema_request, lambda response: response['result']['data'] is not None)
    return await ledger.parse_get_schema_response(get_schema_response)


async def get_cred_def(pool_handle, _did, cred_def_id):
    get_cred_def_request = await ledger.build_get_cred_def_request(_did, cred_def_id)
    get_cred_def_response = \
        await ensure_previous_request_applied(pool_handle, get_cred_def_request,
                                              lambda response: response['result']['data'] is not None)
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

    print("\n University issues credential to Alice")
    # We can use almost any encoding scheme
    theUniversity['alice_transcript_cred_values'] = json.dumps({
        "first_name": {"raw": "Alice", "encoded": "1139481716457488690172217916278103335"},
        "last_name": {"raw": "Garcia", "encoded": "5321642780241790123587902456789123452"},
        "degree": {"raw": "Bachelor of Science, Marketing", "encoded": "12434523576212321"},
        "status": {"raw": "graduated", "encoded": "2213454313412354"},
        "ssn": {"raw": "123-45-6789", "encoded": "3124141231422543541"},
        "year": {"raw": "2015", "encoded": "2015"},
        "average": {"raw": "5", "encoded": "5"}
    })
    theUniversity['transcript_cred'], _,_ = \
        await anoncreds.issuer_create_credential(theUniversity['wallet'], theUniversity['transcript_cred_offer'], theUniversity['transcript_cred_request'],
                                                 theUniversity['alice_transcript_cred_values'], None, None)
    
    print("\nUniversity transcript credential\n")
    print(theUniversity['transcript_cred'])

    # Over the network
    alice['transcript_cred'] = theUniversity['transcript_cred']
    _, alice['transcript_cred_def'] = await get_cred_def(alice['pool'], alice['did'], alice['transcript_cred_def_id'])
    await anoncreds.prover_store_credential(alice['wallet'], None, alice['transcript_cred_request_metadata'], alice['transcript_cred'], alice['transcript_cred_def'], None)
    print("\n Alice transcript credential\n")
    print(alice['transcript_cred_def'])

    print("\n-------------------------")
    print("STEP 7: Alice makes verifiable presentation to Company")
    print("-------------------------")

        # Creating application request (presentaion request) --- validator - theCompany
    nonce = await anoncreds.generate_nonce()
    theCompany['job_application_proof_request'] = json.dumps({
        'nonce': nonce,
        'name': 'Job-Application',
        'version': '0.1',
        'requested_attributes': {
            'attr1_referent': {
                'name': 'first_name'
            },
            'attr2_referent': {
                'name': 'last_name'
            },
            'attr3_referent': {
                'name': 'degree',
                'restrictions': [{'cred_def_id': theUniversity['transcript_cred_def_id']}]
            },
            'attr4_referent': {
                'name': 'status',
                'restrictions': [{'cred_def_id': theUniversity['transcript_cred_def_id']}]
            },
            'attr5_referent': {
                'name': 'ssn',
                'restrictions': [{'cred_def_id': theUniversity['transcript_cred_def_id']}]
            },
            'attr6_referent': {
                'name': 'phone_number'
            }
        },
        'requested_predicates': {
            'predicate1_referent': {
                'name': 'average',
                'p_type': '>=',
                'p_value': 4,
                'restrictions': [{'cred_def_id': theUniversity['transcript_cred_def_id']}]
            }
        }
    })

    # Over network
    alice['job_application_proof_request'] = theCompany['job_application_proof_request']

    # Alice prepares the presentation
    search_for_job_application_proof_request = \
        await anoncreds.prover_search_credentials_for_proof_req(alice['wallet'], alice['job_application_proof_request'], None)

    print("---------------------------")
    print(search_for_job_application_proof_request)
    print("---------------------------")

    cred_for_attr1 = await get_credential_for_referent(search_for_job_application_proof_request, 'attr1_referent')
    cred_for_attr2 = await get_credential_for_referent(search_for_job_application_proof_request, 'attr2_referent')
    cred_for_attr3 = await get_credential_for_referent(search_for_job_application_proof_request, 'attr3_referent')
    cred_for_attr4 = await get_credential_for_referent(search_for_job_application_proof_request, 'attr4_referent')
    cred_for_attr5 = await get_credential_for_referent(search_for_job_application_proof_request, 'attr5_referent')
    # Predicate is the condition to issue for zero knowledge pool
    cred_for_predicate1 = \
        await get_credential_for_referent(search_for_job_application_proof_request, 'predicate1_referent')
    
    print("---------------------------")
    print(cred_for_attr1)
    print("---------------------------")

    await anoncreds.prover_close_credentials_search_for_proof_req(search_for_job_application_proof_request)

    alice['creds_for_job_application_proof'] = {cred_for_attr1['referent']: cred_for_attr1,
                                                cred_for_attr2['referent']: cred_for_attr2,
                                                cred_for_attr3['referent']: cred_for_attr3,
                                                cred_for_attr4['referent']: cred_for_attr4,
                                                cred_for_attr5['referent']: cred_for_attr5,
                                                cred_for_predicate1['referent']: cred_for_predicate1}
    print("\nCredentials for Alice\n")
    print(alice['creds_for_job_application_proof'])

loop = asyncio.get_event_loop()
loop.run_until_complete(run())
