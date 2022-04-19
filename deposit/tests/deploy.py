from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.future import transaction


#private_key, public_address = account.generate_account()

algod_address = "https://testnet-algorand.api.purestake.io/ps2"
algod_token = "rw0sHyrj9h5Fvro77Jpvu1uFHIyUWY8o5pTeSMWE"
headers = {
   "X-API-Key": algod_token,
}
# initialize an algodClient
algod_client = algod.AlgodClient(algod_token, algod_address, headers)

print(algod_client.status())

# create app


#
