import asyncio
import json

from indy import pool
from indy.error import ErrorCode, IndyError

async def run():
    print("Indy demo program")

    print("STEP 1: Connect to pool")
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

    print("STEP 2: Configuring steward")

    steward = {
        'name': "Sovrin steward",
        'wallet_config': json.dumps({ 'id': ' sovrin_steward_wallet '}),
        'wallet_credentials': json.dumps({ 'key': ' steward_wallet_key '}),
        'pool': pool_handle,
        'seed': '000000000000000000000000Steward1'
    }
    print(steward)

loop = asyncio.get_event_loop()
loop.run_until_complete(run())
