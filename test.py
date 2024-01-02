import asyncio
import json
from flask import Flask, request, jsonify

import json
import time
from typing import Dict, List, Union

from indy import pool, wallet, did, ledger, anoncreds, blob_storage
from indy.error import ErrorCode, IndyError
from indy.pairwise import get_pairwise

from os.path import dirname

app = Flask(__name__)


async def verifier_get_entities_from_ledger(pool_handle, _did, identifiers, actor, timestamp=None):
    schemas = {}
    cred_defs = {}
    rev_reg_defs = {}
    rev_regs = {}
    for item in identifiers:
        print("\"{}\" -> Get Schema from Ledger".format(actor))
        (received_schema_id, received_schema) = await get_schema(pool_handle, _did, item['schema_id'])
        schemas[received_schema_id] = json.loads(received_schema)

        print("\"{}\" -> Get Claim Definition from Ledger".format(actor))
        (received_cred_def_id, received_cred_def) = await get_cred_def(pool_handle, _did, item['cred_def_id'])
        cred_defs[received_cred_def_id] = json.loads(received_cred_def)

        if 'rev_reg_id' in item and item['rev_reg_id'] is not None:
            # Get Revocation Definitions and Revocation Registries
            print("\"{}\" -> Get Revocation Definition from Ledger".format(actor))
            get_revoc_reg_def_request = await ledger.build_get_revoc_reg_def_request(_did, item['rev_reg_id'])

            get_revoc_reg_def_response = \
                await ensure_previous_request_applied(pool_handle, get_revoc_reg_def_request,
                                                      lambda response: response['result']['data'] is not None)
            (rev_reg_id, revoc_reg_def_json) = await ledger.parse_get_revoc_reg_def_response(get_revoc_reg_def_response)

            print("\"{}\" -> Get Revocation Registry from Ledger".format(actor))
            if not timestamp: timestamp = item['timestamp']
            get_revoc_reg_request = \
                await ledger.build_get_revoc_reg_request(_did, item['rev_reg_id'], timestamp)
            get_revoc_reg_response = \
                await ensure_previous_request_applied(pool_handle, get_revoc_reg_request,
                                                      lambda response: response['result']['data'] is not None)
            (rev_reg_id, rev_reg_json, timestamp2) = await ledger.parse_get_revoc_reg_response(get_revoc_reg_response)

            rev_regs[rev_reg_id] = {timestamp2: json.loads(rev_reg_json)}
            rev_reg_defs[rev_reg_id] = json.loads(revoc_reg_def_json)

    return json.dumps(schemas), json.dumps(cred_defs), json.dumps(rev_reg_defs), json.dumps(rev_regs)


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


async def ensure_previous_request_applied(pool_handle, checker_request, checker):
    for _ in range(3):
        response = json.loads(await ledger.submit_request(pool_handle, checker_request))
        try:
            if checker(response):
                return json.dumps(response)
        except TypeError:
            pass
        time.sleep(5)


async def create_wallet(identity):
    print("\"{}\" -> Create wallet".format(identity['name']))
    try:
        await wallet.create_wallet(identity['wallet_config'],
                                   identity['wallet_credentials'])
    except IndyError as ex:
        if ex.error_code == ErrorCode.PoolLedgerConfigAlreadyExistsError:
            pass
    identity['wallet'] = await wallet.open_wallet(identity['wallet_config'],
                                                  identity['wallet_credentials'])


async def getting_verinym(from_, to):
    await create_wallet(to)

    (to['did'], to['key']) = await did.create_and_store_my_did(to['wallet'], "{}")

    from_['info'] = {
        'did': to['did'],
        'verkey': to['key'],
        'role': to['role'] or None
    }

    await send_nym(from_['pool'], from_['wallet'], from_['did'], from_['info']['did'],
                   from_['info']['verkey'], from_['info']['role'])


async def send_nym(pool_handle, wallet_handle, _did, new_did, new_key, role):
    nym_request = await ledger.build_nym_request(_did, new_did, new_key, None, role)
    print(nym_request)
    await ledger.sign_and_submit_request(pool_handle, wallet_handle, _did, nym_request)


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

async def run():
    print("**************")
    global pool_
    pool_ = {
        'name': 'pool1'
    }
    print("Open Pool Ledger: {}".format(pool_['name']))
    pool_['genesis_txn_path'] = "pool1.txn"
    pool_['config'] = json.dumps({"genesis_txn": str(pool_['genesis_txn_path'])})

    print(pool_)

    # Set protocol version 2 to work with Indy Node 1.4
    await pool.set_protocol_version(2)

    try:
        await pool.create_pool_ledger_config(pool_['name'], pool_['config'])
    except IndyError as ex:
        if ex.error_code == ErrorCode.PoolLedgerConfigAlreadyExistsError:
            pass
    pool_['handle'] = await pool.open_pool_ledger(pool_['name'], None)

    print(pool_['handle'])

@app.route("/create_wallet", methods=["POST"])
async def create_wallet_1():
    try: 
        data = request.get_json()

        steward = {
            'name': data["name"],
            'wallet_config': json.dumps({'id': data["wallet_config"]}),
            'wallet_credentials': json.dumps({'key': data["wallet_credentials"]}),
            'pool': pool_['handle'],
            'seed': data["seed"]
        }

        create_wallet(steward)

        steward["did_info"] = json.dumps({'seed': steward['seed']})
        steward['did'], steward['key'] = await did.create_and_store_my_did(steward['wallet'], steward['did_info'])

        return jsonify({"status_code": 200, "detail": steward})
    except Exception as e:
        print(e)

@app.route("/register_dids_government", methods=["POST"])
async def register_dids_government():
    data = request.get_json()

    government = {
        'name': data['name'],
        'wallet_config': json.dumps({'id': data['wallet_config']}),
        'wallet_credentials': json.dumps({'key': data['wallet_credentials']}),
        'pool': pool_['handle'],
        'role': data['role']
    }

    # Assuming getting_verinym is a function that does the work
    await getting_verinym(data['steward'], government)

    return jsonify({"status_code": 200, "detail": "Success"})

@app.route("/register_dids_university", methods=["POST"])
async def register_dids_university():
    data = request.get_json()

    the_university = {
        'name': data['name'],
        'wallet_config': json.dumps({'id': data['wallet_config']}),
        'wallet_credentials': json.dumps({'key': data['wallet_credentials']}),
        'pool': pool_['handle'],
        'role': data['role']
    }

    await getting_verinym(data['steward'], the_university)

    return jsonify({"status_code": 200, "detail": "Success"})


@app.route("/register_dids_company", methods=["POST"])
async def register_dids_company():
    data = request.get_json()

    the_company = {
        'name': data['name'],
        'wallet_config': json.dumps({'id': data['wallet_config']}),
        'wallet_credentials': json.dumps({'key': data['wallet_credentials']}),
        'pool': pool_['handle'],
        'role': data['role']
    }

    await getting_verinym(data['steward'], the_company)

    return jsonify({"status_code": 200, "detail": "Success"})

@app.route("/government_transcript_schema", methods=["POST"])
async def government_transcript_schema():
    data = request.get_json()

    transcript = {
        'name': data['name'],
        'version': data['version'],
        'attributes': data['attributes']
    }

    (request.government['transcript_schema_id'], request.government['transcript_schema']) = \
        await anoncreds.issuer_create_schema(request.government['did'], transcript['name'], transcript['version'],
                                             json.dumps(transcript['attributes']))
    
    schema_request = await ledger.build_schema_request(request.government['did'], request.government['transcript_schema'])
    await ledger.sign_and_submit_request(request.government['pool'], request.government['wallet'], request.government['did'], schema_request)

    return jsonify({"status_code": 200, "detail": "Success"})

@app.route("/university_credential_definition", methods=["POST"])
async def university_credential_definition():
    data = request.get_json()

    get_schema_request = await ledger.build_get_schema_request(request.university['did'], request.government["transcript_schema_id"])
    get_schema_response = await ensure_previous_request_applied(
        request.university['pool'], get_schema_request, lambda response: response['result']['data'] is not None)
    (request.university['transcript_schema_id'], request.university['transcript_schema']) = await ledger.parse_get_schema_response(get_schema_response)

    transcript_cred_def = {
        'tag': request.transcript_cred_tag,
        'type': request.transcript_cred_type,
        'config': request.transcript_cred_config
    }
    (request.university['transcript_cred_def_id'], request.university['transcript_cred_def']) = \
        await anoncreds.issuer_create_and_store_credential_def(request.university['wallet'], request.university['did'],
                                                               request.university['transcript_schema'], transcript_cred_def['tag'],
                                                               transcript_cred_def['type'],
                                                               json.dumps(transcript_cred_def['config']))
    
    cred_def_request = await ledger.build_cred_def_request(request.university['did'], request.university['transcript_cred_def'])

    await ledger.sign_and_submit_request(request.university['pool'], request.university['wallet'], request.university['did'], cred_def_request)

    return jsonify({"status_code": 200, "detail": "Success"})

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run())
    app.run(port=5000)