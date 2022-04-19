from typing import Tuple

from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction
from algosdk.logic import get_application_address

from .account import Account
from deposit.contracts.contracts import approval_program, clear_state_program
from .utils import (
    waitForTransaction,
    fullyCompileContract,
    getAppGlobalState,
    getBalances,
)

APPROVAL_PROGRAM = b""
CLEAR_STATE_PROGRAM = b""

""" MIN_BALANCE_REQUIREMENT = (
    # min account balance
    100_000
    # additional min balance for 3 assets
    + 100_000 * 3
) """


def getContracts(client: AlgodClient) -> Tuple[bytes, bytes]:
    """Get the compiled TEAL contracts for the amm.
    Args:q
        client: An algod client that has the ability to compile TEAL programs.
    Returns:
        A tuple of 2 byte strings. The first is the approval program, and the
        second is the clear state program.
    """
    global APPROVAL_PROGRAM
    global CLEAR_STATE_PROGRAM

    if len(APPROVAL_PROGRAM) == 0:
        APPROVAL_PROGRAM = fullyCompileContract(client, approval_program())
        CLEAR_STATE_PROGRAM = fullyCompileContract(client, clear_state_program())

    return APPROVAL_PROGRAM, CLEAR_STATE_PROGRAM


def createApp(
    client: AlgodClient,
    creator: Account,
) -> int:
    """Create a new amm.
    Args:
        client: An algod client.
        creator: The account that will create the deposit application.
    Returns:
        The ID of the newly created amm app.
    """
    approval, clear = getContracts(client)

    globalSchema = transaction.StateSchema(num_uints=0, num_byte_slices=0)
    localSchema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    txn = transaction.ApplicationCreateTxn(
        sender=creator.getAddress(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=globalSchema,
        local_schema=localSchema,
        sp=client.suggested_params(),
    )

    signedTxn = txn.sign(creator.getPrivateKey())

    client.send_transaction(signedTxn)

    response = waitForTransaction(client, signedTxn.get_txid())
    assert response.applicationIndex is not None and response.applicationIndex > 0
    return response.applicationIndex


def deposit_asa(
    client: AlgodClient,
    appID: int,
    funder: Account,
    token: int,
) -> int:
    """Finish setting up deposit app.
    This operation funds the pool account, creates pool token,
    and opts app into tokens A and B, all in one atomic transaction group.
    Args:
        client: An algod client.
        appID: The app ID of the amm.
        funder: The account providing the funding for the escrow account.
        tokenA: Token A id.
        tokenB: Token B id.
    Return: pool token id
    """
    appAddr = get_application_address(appID)

    suggestedParams = client.suggested_params()

    fundingAmount = (1_000)

    fundAppTxn = transaction.PaymentTxn(
        sender=funder.getAddress(),
        receiver=appAddr,
        amt=fundingAmount,
        sp=suggestedParams,
    )
#decouple this two
    setupTxn = transaction.ApplicationCallTxn(
        sender=funder.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"asa_deposit"],
        #foreign_assets=[tokenA, tokenB],
        sp=suggestedParams,
    )

    transaction.assign_group_id([fundAppTxn, setupTxn])

    signedFundAppTxn = fundAppTxn.sign(funder.getPrivateKey())
    signedSetupTxn = setupTxn.sign(funder.getPrivateKey())

    client.send_transactions([signedFundAppTxn, signedSetupTxn])

    response = waitForTransaction(client, signedFundAppTxn.get_txid())

    return response


def supply(
    client: AlgodClient, appID: int, qA: int, qB: int, supplier: Account
) -> None:
    """Supply liquidity to the pool.
    Let rA, rB denote the existing pool reserves of token A and token B respectively
    First supplier will receive sqrt(qA*qB) tokens, subsequent suppliers will receive
    qA/rA where rA is the amount of token A already in the pool.
    If qA/qB != rA/rB, the pool will first attempt to take full amount qA, returning excess token B
    Else if there is insufficient amount qB, the pool will then attempt to take the full amount qB, returning
     excess token A
    Else transaction will be rejected
    Args:
        client: AlgodClient,
        appID: amm app id,
        qA: amount of token A to supply the pool
        qB: amount of token B to supply to the pool
        supplier: supplier account
    """
    assertSetup(client, appID)
    appAddr = get_application_address(appID)
    appGlobalState = getAppGlobalState(client, appID)
    suggestedParams = client.suggested_params()

    tokenA = appGlobalState[b"token_a_key"]
    tokenB = appGlobalState[b"token_b_key"]
    poolToken = getPoolTokenId(appGlobalState)

    # pay for the fee incurred by AMM for sending back the pool token
    feeTxn = transaction.PaymentTxn(
        sender=supplier.getAddress(),
        receiver=appAddr,
        amt=2_000,
        sp=suggestedParams,
    )

    tokenATxn = transaction.AssetTransferTxn(
        sender=supplier.getAddress(),
        receiver=appAddr,
        index=tokenA,
        amt=qA,
        sp=suggestedParams,
    )
    tokenBTxn = transaction.AssetTransferTxn(
        sender=supplier.getAddress(),
        receiver=appAddr,
        index=tokenB,
        amt=qB,
        sp=suggestedParams,
    )

    appCallTxn = transaction.ApplicationCallTxn(
        sender=supplier.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"supply"],
        foreign_assets=[tokenA, tokenB, poolToken],
        sp=suggestedParams,
    )

    transaction.assign_group_id([feeTxn, tokenATxn, tokenBTxn, appCallTxn])
    signedFeeTxn = feeTxn.sign(supplier.getPrivateKey())
    signedTokenATxn = tokenATxn.sign(supplier.getPrivateKey())
    signedTokenBTxn = tokenBTxn.sign(supplier.getPrivateKey())
    signedAppCallTxn = appCallTxn.sign(supplier.getPrivateKey())

    client.send_transactions(
        [signedFeeTxn, signedTokenATxn, signedTokenBTxn, signedAppCallTxn]
    )
    waitForTransaction(client, signedAppCallTxn.get_txid())


def withdraw(
    client: AlgodClient, appID: int, poolTokenAmount: int, withdrawAccount: Account
) -> None:
    """Withdraw liquidity  + rewards from the pool back to supplier.
    Supplier should receive tokenA, tokenB + fees proportional to the liquidity share in the pool they choose to withdraw.
    Args:
        client: AlgodClient,
        appID: amm app id,
        poolTokenAmount: pool token quantity,
        withdrawAccount: supplier account,
    """
    assertSetup(client, appID)
    appAddr = get_application_address(appID)
    appGlobalState = getAppGlobalState(client, appID)
    suggestedParams = client.suggested_params()

    # pay for the fee incurred by AMM for sending back tokens A and B
    feeTxn = transaction.PaymentTxn(
        sender=withdrawAccount.getAddress(),
        receiver=appAddr,
        amt=2_000,
        sp=suggestedParams,
    )

    tokenA = appGlobalState[b"token_a_key"]
    tokenB = appGlobalState[b"token_b_key"]
    poolToken = getPoolTokenId(appGlobalState)

    poolTokenTxn = transaction.AssetTransferTxn(
        sender=withdrawAccount.getAddress(),
        receiver=appAddr,
        index=poolToken,
        amt=poolTokenAmount,
        sp=suggestedParams,
    )

    appCallTxn = transaction.ApplicationCallTxn(
        sender=withdrawAccount.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"withdraw"],
        foreign_assets=[tokenA, tokenB, poolToken],
        sp=suggestedParams,
    )

    transaction.assign_group_id([feeTxn, poolTokenTxn, appCallTxn])
    signedFeeTxn = feeTxn.sign(withdrawAccount.getPrivateKey())
    signedPoolTokenTxn = poolTokenTxn.sign(withdrawAccount.getPrivateKey())
    signedAppCallTxn = appCallTxn.sign(withdrawAccount.getPrivateKey())

    client.send_transactions([signedFeeTxn, signedPoolTokenTxn, signedAppCallTxn])
    waitForTransaction(client, signedAppCallTxn.get_txid())


def swap(client: AlgodClient, appID: int, tokenId: int, amount: int, trader: Account):
    """Swap tokenId token for the other token in the pool
    This action can only happen if there is liquidity in the pool
    A fee (in bps, configured on app creation) is taken out of the input amount before calculating the output amount
    """
    assertSetup(client, appID)
    appAddr = get_application_address(appID)
    appGlobalState = getAppGlobalState(client, appID)
    suggestedParams = client.suggested_params()

    feeTxn = transaction.PaymentTxn(
        sender=trader.getAddress(),
        receiver=appAddr,
        amt=1000,
        sp=suggestedParams,
    )

    tokenA = appGlobalState[b"token_a_key"]
    tokenB = appGlobalState[b"token_b_key"]

    tradeTxn = transaction.AssetTransferTxn(
        sender=trader.getAddress(),
        receiver=appAddr,
        index=tokenId,
        amt=amount,
        sp=suggestedParams,
    )

    appCallTxn = transaction.ApplicationCallTxn(
        sender=trader.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"swap"],
        foreign_assets=[tokenA, tokenB],
        sp=suggestedParams,
    )

    transaction.assign_group_id([feeTxn, tradeTxn, appCallTxn])
    signedFeeTxn = feeTxn.sign(trader.getPrivateKey())
    signedTradeTxn = tradeTxn.sign(trader.getPrivateKey())
    signedAppCallTxn = appCallTxn.sign(trader.getPrivateKey())

    client.send_transactions([signedFeeTxn, signedTradeTxn, signedAppCallTxn])
    waitForTransaction(client, signedAppCallTxn.get_txid())


def closeAmm(client: AlgodClient, appID: int, closer: Account):
    """Close an amm.
    This action can only happen if there is no liquidity in the pool (outstanding pool tokens = 0).
    Args:
        client: An Algod client.
        appID: The app ID of the amm.
        closer: closer account. Must be the original creator of the pool.
    """

    deleteTxn = transaction.ApplicationDeleteTxn(
        sender=closer.getAddress(),
        index=appID,
        sp=client.suggested_params(),
    )
    signedDeleteTxn = deleteTxn.sign(closer.getPrivateKey())

    client.send_transaction(signedDeleteTxn)

    waitForTransaction(client, signedDeleteTxn.get_txid())


def getPoolTokenId(appGlobalState):
    try:
        return appGlobalState[b"pool_token_key"]
    except KeyError:
        raise RuntimeError(
            "Pool token id doesn't exist. Make sure the app has been set up"
        )


def assertSetup(client: AlgodClient, appID: int) -> None:
    balances = getBalances(client, get_application_address(appID))
    assert (
        balances[0] >= MIN_BALANCE_REQUIREMENT
    ), "AMM must be set up and funded first. AMM balances: " + str(balances)