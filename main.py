import asyncio
import json

from indy import pool
from indy.error import ErrorCode, IndyError

async def run(): 
    print("Indy demo program")

    # print("STEP 1")
    # pool = {
    #     "name": "pool1"
    # }

    # print("Open pool ledger: {}".format(pool ['name']))
    # pool ['genesis txn path'] = "pool1.txn"
    # pool ['config'] = json.dumps({"genesis_txn": str(pool ['genesis txn path'])})

    # print(pool)

    # connect to pool
    await pool.set_protocol_version(2)
    try: 
        await pool.create_pool_ledger_config(pool_['name'], pool_['config'])
    except IndyError as ex:
        if ex.error_code == ErrorCode.PoolLedgerConfigAlreadyExistsError:
            pass
    pool_['handle'] = await pool.open_pool_ledger(pool_['name'], None)

    print(pool_['handle'])

loop = asyncio.get_event_loop()
loop.run_until_complete(run())