from time import time, sleep

from algosdk import account, encoding
from algosdk.logic import get_application_address
""" from amm.operations import (
    createAmmApp,
    setupAmmApp,
    supply,
    withdraw,
    swap,
    closeAmm,
    optInToPoolToken,
)
from amm.util import (
    getBalances,
    getAppGlobalState,
    getLastBlockTimestamp,
)
from amm.testing.setup import getAlgodClient
from amm.testing.resources import (
    getTemporaryAccount,
    optInToAsset,
    createDummyAsset,
) """

def simple_amm():
    client = getAlgodClient()

    print("Alice is generating temporary accounts...")
    creator = getTemporaryAccount(client)
    supplier = getTemporaryAccount(client)

    print("Alice is generating example tokens...")
    tokenAAmount = 10 ** 13
    tokenBAmount = 10 ** 13
    tokenA = createDummyAsset(client, tokenBAmount, creator)
    tokenB = createDummyAsset(client, tokenBAmount, creator)
    print("TokenA id is:", tokenA)
    print("TokenB id is:", tokenB)

    print("Alice is creating AMM that swaps between token A and token B...")
    appID = createAmmApp(
        client=client,
        creator=creator,
        tokenA=tokenA,
        tokenB=tokenB,
        feeBps=30,
        minIncrement=1000,
    )

    creatorBalancesBefore = getBalances(client, creator.getAddress())
    ammBalancesBefore = getBalances(client, get_application_address(appID))

    print("Alice's balances: ", creatorBalancesBefore)
    print("AMM's balances: ", ammBalancesBefore)

    print("Alice is setting up and funding amm...")
    poolToken = setupAmmApp(
        client=client,
        appID=appID,
        funder=creator,
        tokenA=tokenA,
        tokenB=tokenB,
    )

    creatorBalancesBefore = getBalances(client, creator.getAddress())
    ammBalancesBefore = getBalances(client, get_application_address(appID))

    print("Alice's balances: ", creatorBalancesBefore)
    print("AMM's balances: ", ammBalancesBefore)
    print("Opting Alice in to receive pool token...")
    optInToPoolToken(client, appID, creator)

    print("Supplying AMM with initial token A and token B")
    supply(client=client, appID=appID, qA=500_000, qB=100_000_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    creatorBalancesSupplied = getBalances(client, creator.getAddress())
    poolTokenFirstAmount = creatorBalancesSupplied[poolToken]
    print("AMM's balances: ", ammBalancesSupplied)
    print("Alice's balances: ", creatorBalancesSupplied)

    print("Supplying AMM with same token A and token B")
    supply(client=client, appID=appID, qA=100_000, qB=20_000_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    creatorBalancesSupplied = getBalances(client, creator.getAddress())

    print("AMM's balances: ", ammBalancesSupplied)
    print("Alice's balances: ", creatorBalancesSupplied)

    print("Supplying AMM with too large ratio of token A and token B")
    supply(client=client, appID=appID, qA=100_000, qB=100_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    creatorBalancesSupplied = getBalances(client, creator.getAddress())
    print("AMM's balances: ", ammBalancesSupplied)
    print("Alice's balances: ", creatorBalancesSupplied)

    print("Supplying AMM with too small ratio of token A and token B")
    supply(client=client, appID=appID, qA=100_000, qB=100_000_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    creatorBalancesSupplied = getBalances(client, creator.getAddress())

    print("AMM's balances: ", ammBalancesSupplied)
    print("Alice's balances: ", creatorBalancesSupplied)
    poolTokenTotalAmount = creatorBalancesSupplied[poolToken]
    print(" ")
    print("Alice is exchanging her Token A for Token B")
    swap(client=client, appID=appID, tokenId=tokenA, amount=1_000, trader=creator)
    ammBalancesTraded = getBalances(client, get_application_address(appID))
    creatorBalancesTraded = getBalances(client, creator.getAddress())
    print("AMM's balances: ", ammBalancesTraded)
    print("Alice's balances: ", creatorBalancesTraded)

    print("Alice is exchanging her Token B for Token A")
    swap(
        client=client,
        appID=appID,
        tokenId=tokenB,
        amount=int(1_000_000 * 1.003),
        trader=creator,
    )
    ammBalancesTraded = getBalances(client, get_application_address(appID))
    creatorBalancesTraded = getBalances(client, creator.getAddress())
    print("AMM's balances: ", ammBalancesTraded)
    print("Alice's balances: ", creatorBalancesTraded)
    print(" ")

    print("Withdrawing first supplied liquidity from AMM")
    print("Withdrawing: ", poolTokenFirstAmount)
    withdraw(
        client=client,
        appID=appID,
        poolTokenAmount=poolTokenFirstAmount,
        withdrawAccount=creator,
    )
    ammBalancesWithdrawn = getBalances(client, get_application_address(appID))
    print("AMM's balances: ", ammBalancesWithdrawn)

    print("Withdrawing remainder of the supplied liquidity from AMM")
    poolTokenTotalAmount -= poolTokenFirstAmount
    withdraw(
        client=client,
        appID=appID,
        poolTokenAmount=poolTokenTotalAmount,
        withdrawAccount=creator,
    )
    ammBalancesWithdrawn = getBalances(client, get_application_address(appID))
    print("AMM's balances: ", ammBalancesWithdrawn)
    print("Closing AMM")
    closeAmm(client=client, appID=appID, closer=creator)


simple_amm()