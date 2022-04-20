from algosdk import account
from algosdk.v2client import algod
from algosdk import account, constants
from algosdk.future import transaction

def intToBytes(i):
    return i.to_bytes(8, "big")

algod_address = "https://testnet-algorand.api.purestake.io/ps2"
algod_token = "rw0sHyrj9h5Fvro77Jpvu1uFHIyUWY8o5pTeSMWE"
headers = {
   "X-API-Key": algod_token,
}
# initialize an algodClient
algod_client = algod.AlgodClient(algod_token, algod_address, headers)


test_private_key = 'NhGFRJy9Hsc1dntdOv78K8VIb/NHwfRTFJXT6+wOVsddPEVEFA1G8FoD2l37+S1BVNUEBaRnSEHldUcuIPPmFA=='
app_id = 84896004
asset_id = 84891710
application_address = 'JLRN2KXRQC3GBBHHVBFY34HECD6BPTZVK4MMBIWKAQVXEJRLXLNCU6DPFE'

print(123)

def call_app(client, private_key, index, app_args, rekey_to, foreign_assets=None):
    # declare sender
    sender = account.address_from_private_key(private_key)
    print("Call from account:", sender)

    # get node suggested parameters
    params = client.suggested_params()
    params.fee = constants.MIN_TXN_FEE

    # create unsigned transaction
    txn = transaction.ApplicationNoOpTxn(sender, 
                                        params, 
                                        index, 
                                        app_args, 
                                        rekey_to=rekey_to,
                                        foreign_assets=foreign_assets)

    # sign transaction
    signed_txn = txn.sign(private_key)
    tx_id = signed_txn.transaction.get_txid()

    # send transaction
    client.send_transactions([signed_txn])

    # await confirmation
    result = wait_for_confirmation(client, tx_id)

    return result

def wait_for_confirmation(client, txid):
    last_round = client.status().get("last-round")
    txinfo = client.pending_transaction_info(txid)
    while not (txinfo.get("confirmed-round") and txinfo.get("confirmed-round") > 0):
        print("Waiting for confirmation...")
        last_round += 1
        client.status_after_block(last_round)
        txinfo = client.pending_transaction_info(txid)
    print(
        "Transaction {} confirmed in round {}.".format(
            txid, txinfo.get("confirmed-round")
        )
    )
    return txinfo


def print_asset_holding(algodclient, account, assetid):
    import json
    account_info = algodclient.account_info(account)
    idx = 0
    for my_account_info in account_info['assets']:
        scrutinized_asset = account_info['assets'][idx]
        idx = idx + 1        
        if (scrutinized_asset['asset-id'] == assetid):
            print("Asset ID: {}".format(scrutinized_asset['asset-id']))
            print(json.dumps(scrutinized_asset, indent=4))
            break

print_asset_holding(algod_client, account.address_from_private_key(test_private_key), asset_id)


""" app_args = [b"deposit", intToBytes(1000)]

call_app(algod_client, 
        test_private_key, 
        app_id, 
        app_args,
        rekey_to=application_address,
        foreign_assets=None
        )  """

def create_asset(client, private_key):
    import json
    # declare sender
    sender = account.address_from_private_key(private_key)

    params = client.suggested_params()

    txn = transaction.AssetConfigTxn(
        sender=sender,
        sp=params,
        total=1_000_000_000,
        default_frozen=False,
        unit_name="C3pio",
        asset_name="C3coin",
        manager=sender,
        reserve=sender,
        freeze=sender,
        clawback=sender,
        strict_empty_address_check=False,
        url=None, 
        decimals=0)

    # Sign with secret key of creator
    stxn = txn.sign(private_key)

    # Send the transaction to the network and retrieve the txid.
    
    txid = client.send_transaction(stxn)
    print("Signed transaction with txID: {}".format(txid))
    # Wait for the transaction to be confirmed
    confirmed_txn = wait_for_confirmation(client, txid)  
    print("TXID: ", txid)
    print("Result confirmed in round: {}".format(confirmed_txn['confirmed-round']))   

    
    # Retrieve the asset ID of the newly created asset by first
    # ensuring that the creation transaction was confirmed,
    # then grabbing the asset id from the transaction.
    print("Transaction information: {}".format(
        json.dumps(confirmed_txn, indent=4)))
    # print("Decoded note: {}".format(base64.b64decode(
    #     confirmed_txn["txn"]["txn"]["note"]).decode()))
    try:
        # Pull account info for the creator
        ptx = client.pending_transaction_info(txid)
        asset_id = ptx["asset-index"]
        print_asset_holding(client, private_key, asset_id)
    except Exception as e:
        print(e)

    return asset_id

""" print(create_asset(algod_client, 
        test_private_key, )) """

#app_args = [b"asa_deposit", intToBytes(1000)]
app_args = [b"asa_deposit", 1000]

call_app(algod_client, 
        test_private_key, 
        app_id, 
        app_args,
        rekey_to=application_address,
        foreign_assets=[asset_id]
        )