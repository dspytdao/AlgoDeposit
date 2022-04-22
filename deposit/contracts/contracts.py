from pyteal import *

# we want to get the swap with one tx
# but we need some leverage to do both txs
# outside token + existing LP token

CREATOR_KEY = Bytes("creator_key")
TOKEN_A_KEY = Bytes("token_a_key")
TOKEN_B_KEY = Bytes("token_b_key")
POOL_TOKEN_KEY = Bytes("pool_token_key")
FEE_BPS_KEY = Bytes("fee_bps_key")
MIN_INCREMENT_KEY = Bytes("min_increment_key")
POOL_TOKENS_OUTSTANDING_KEY = Bytes("pool_tokens_outstanding_key")
SCALING_FACTOR = Int(10 ** 13)
POOL_TOKEN_DEFAULT_AMOUNT = Int(10 ** 13)


def validateTokenReceived(
    transaction_index: TealType.uint64, token_key: TealType.bytes
) -> Expr:
    return And(
        Gtxn[transaction_index].type_enum() == TxnType.AssetTransfer,
        Gtxn[transaction_index].sender() == Txn.sender(),
        Gtxn[transaction_index].asset_receiver()
        == Global.current_application_address(),
        Gtxn[transaction_index].xfer_asset() == App.globalGet(token_key),
        Gtxn[transaction_index].asset_amount() > Int(0),
    )


def xMulYDivZ(x, y, z) -> Expr:
    return WideRatio([x, y, SCALING_FACTOR], [z, SCALING_FACTOR])


def sendToken(
    token_key: TealType.bytes, receiver: TealType.bytes, amount: TealType.uint64
) -> Expr:
    return Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(token_key),
                TxnField.asset_receiver: receiver,
                TxnField.asset_amount: amount,
            }
        ),
        InnerTxnBuilder.Submit(),
    )



def createPoolToken(pool_token_amount: TealType.uint64) -> Expr:
    return Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetConfig,
                TxnField.config_asset_total: pool_token_amount,
                TxnField.config_asset_default_frozen: Int(0),
                TxnField.config_asset_decimals: Int(0),
                TxnField.config_asset_reserve: Global.current_application_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        App.globalPut(POOL_TOKEN_KEY, InnerTxn.created_asset_id()),
        App.globalPut(POOL_TOKENS_OUTSTANDING_KEY, Int(0)),
    )



def optIn(token_key: TealType.bytes) -> Expr:
    return sendToken(token_key, Global.current_application_address(), Int(0))



def returnRemainder(
    token_key: TealType.bytes,
    received_amount: TealType.uint64,
    to_keep_amount: TealType.uint64,
) -> Expr:
    remainder = received_amount - to_keep_amount
    return Seq(
        If(remainder > Int(0)).Then(
            sendToken(
                token_key,
                Txn.sender(),
                remainder,
            )
        ),
    )



def tryTakeAdjustedAmounts(
    to_keep_token_txn_amt: TealType.uint64,
    to_keep_token_before_txn_amt: TealType.uint64,
    other_token_key: TealType.bytes,
    other_token_txn_amt: TealType.uint64,
    other_token_before_txn_amt: TealType.uint64,
) -> Expr:
    """
    Given supplied token amounts, try to keep all of one token and the corresponding amount of other token
    as determined by market price before transaction. If corresponding amount is less than supplied, send the remainder back.
    If successful, mint and sent pool tokens in proportion to new liquidity over old liquidity.
    """
    other_corresponding_amount = ScratchVar(TealType.uint64)

    return Seq(
        other_corresponding_amount.store(
            xMulYDivZ(
                to_keep_token_txn_amt,
                other_token_before_txn_amt,
                to_keep_token_before_txn_amt,
            )
        ),
        If(
            And(
                other_corresponding_amount.load() > Int(0),
                other_token_txn_amt >= other_corresponding_amount.load(),
            )
        ).Then(
            Seq(
                returnRemainder(
                    other_token_key,
                    other_token_txn_amt,
                    other_corresponding_amount.load(),
                ),
                mintAndSendPoolToken(
                    Txn.sender(),
                    xMulYDivZ(
                        App.globalGet(POOL_TOKENS_OUTSTANDING_KEY),
                        to_keep_token_txn_amt,
                        to_keep_token_before_txn_amt,
                    ),
                ),
                Return(Int(1)),
            )
        ),
        Return(Int(0)),
    )



def withdrawGivenPoolToken(
    receiver: TealType.bytes,
    to_withdraw_token_key: TealType.bytes,
    pool_token_amount: TealType.uint64,
    pool_tokens_outstanding: TealType.uint64,
) -> Expr:
    token_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(to_withdraw_token_key)
    )
    return Seq(
        token_holding,
        If(
            And(
                pool_tokens_outstanding > Int(0),
                pool_token_amount > Int(0),
                token_holding.hasValue(),
                token_holding.value() > Int(0),
            )
        ).Then(
            Seq(
                Assert(
                    xMulYDivZ(
                        token_holding.value(),
                        pool_token_amount,
                        pool_tokens_outstanding,
                    )
                    > Int(0)
                ),
                sendToken(
                    to_withdraw_token_key,
                    receiver,
                    xMulYDivZ(
                        token_holding.value(),
                        pool_token_amount,
                        pool_tokens_outstanding,
                    ),
                ),
            )
        ),
    )



def assessFee(amount: TealType.uint64, fee_bps: TealType.uint64):
    fee_num = Int(10000) - fee_bps
    fee_denom = Int(10000)
    return xMulYDivZ(amount, fee_num, fee_denom)



def computeOtherTokenOutputPerGivenTokenInput(
    input_amount: TealType.uint64,
    previous_given_token_amount: TealType.uint64,
    previous_other_token_amount: TealType.uint64,
    fee_bps: TealType.uint64,
):
    k = previous_given_token_amount * previous_other_token_amount
    amount_sub_fee = assessFee(input_amount, fee_bps)
    to_send = previous_other_token_amount - k / (
        previous_given_token_amount + amount_sub_fee
    )
    return to_send



def mintAndSendPoolToken(receiver: TealType.bytes, amount: TealType.uint64) -> Expr:
    return Seq(
        sendToken(POOL_TOKEN_KEY, receiver, amount),
        App.globalPut(
            POOL_TOKENS_OUTSTANDING_KEY,
            App.globalGet(POOL_TOKENS_OUTSTANDING_KEY) + amount,
        ),
    )






def get_setup_program():
    # if the amm has been set up, pool token id and outstanding value already exists
    pool_token_id = App.globalGetEx(Global.current_application_id(), POOL_TOKEN_KEY)
    pool_tokens_outstanding = App.globalGetEx(
        Global.current_application_id(), POOL_TOKENS_OUTSTANDING_KEY
    )
    return Seq(
        pool_token_id,
        pool_tokens_outstanding,
        # can only set up once
        Assert(Not(pool_token_id.hasValue())),
        Assert(Not(pool_tokens_outstanding.hasValue())),
        createPoolToken(POOL_TOKEN_DEFAULT_AMOUNT),
        optIn(TOKEN_A_KEY),
        optIn(TOKEN_B_KEY),
        Approve(),
    )


token_a_holding = AssetHolding.balance(
    Global.current_application_address(), App.globalGet(TOKEN_A_KEY)
)
token_b_holding = AssetHolding.balance(
    Global.current_application_address(), App.globalGet(TOKEN_B_KEY)
)


def get_supply_program():
    token_a_txn_index = Txn.group_index() - Int(2)
    token_b_txn_index = Txn.group_index() - Int(1)

    pool_token_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(POOL_TOKEN_KEY)
    )

    token_a_before_txn: ScratchVar = ScratchVar(TealType.uint64)
    token_b_before_txn: ScratchVar = ScratchVar(TealType.uint64)

    on_supply = Seq(
        pool_token_holding,
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                pool_token_holding.hasValue(),
                pool_token_holding.value() > Int(0),
                validateTokenReceived(token_a_txn_index, TOKEN_A_KEY),
                validateTokenReceived(token_b_txn_index, TOKEN_B_KEY),
                Gtxn[token_a_txn_index].asset_amount()
                >= App.globalGet(MIN_INCREMENT_KEY),
                Gtxn[token_b_txn_index].asset_amount()
                >= App.globalGet(MIN_INCREMENT_KEY),
            )
        ),
        token_a_before_txn.store(
            token_a_holding.value() - Gtxn[token_a_txn_index].asset_amount()
        ),
        token_b_before_txn.store(
            token_b_holding.value() - Gtxn[token_b_txn_index].asset_amount()
        ),
        If(
            Or(
                token_a_before_txn.load() == Int(0),
                token_b_before_txn.load() == Int(0),
            )
        )
        .Then(
            # no liquidity yet, take everything
            Seq(
                mintAndSendPoolToken(
                    Txn.sender(),
                    Sqrt(
                        Gtxn[token_a_txn_index].asset_amount()
                        * Gtxn[token_b_txn_index].asset_amount()
                    ),
                ),
                Approve(),
            ),
        )
        .ElseIf(
            tryTakeAdjustedAmounts(
                Gtxn[token_a_txn_index].asset_amount(),
                token_a_before_txn.load(),
                TOKEN_B_KEY,
                Gtxn[token_b_txn_index].asset_amount(),
                token_b_before_txn.load(),
            )
        )
        .Then(Approve())
        .ElseIf(
            tryTakeAdjustedAmounts(
                Gtxn[token_b_txn_index].asset_amount(),
                token_b_before_txn.load(),
                TOKEN_A_KEY,
                Gtxn[token_a_txn_index].asset_amount(),
                token_a_before_txn.load(),
            ),
        )
        .Then(Approve())
        .Else(Reject()),
    )
    return on_supply


def get_withdraw_program():
    pool_token_txn_index = Txn.group_index() - Int(1)
    on_withdraw = Seq(
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                token_a_holding.hasValue(),
                token_a_holding.value() > Int(0),
                token_b_holding.hasValue(),
                token_b_holding.value() > Int(0),
                validateTokenReceived(pool_token_txn_index, POOL_TOKEN_KEY),
            )
        ),
        If(Gtxn[pool_token_txn_index].asset_amount() > Int(0)).Then(
            Seq(
                withdrawGivenPoolToken(
                    Txn.sender(),
                    TOKEN_A_KEY,
                    Gtxn[pool_token_txn_index].asset_amount(),
                    App.globalGet(POOL_TOKENS_OUTSTANDING_KEY),
                ),
                withdrawGivenPoolToken(
                    Txn.sender(),
                    TOKEN_B_KEY,
                    Gtxn[pool_token_txn_index].asset_amount(),
                    App.globalGet(POOL_TOKENS_OUTSTANDING_KEY),
                ),
                App.globalPut(
                    POOL_TOKENS_OUTSTANDING_KEY,
                    App.globalGet(POOL_TOKENS_OUTSTANDING_KEY)
                    - Gtxn[pool_token_txn_index].asset_amount(),
                ),
                Approve(),
            ),
        ),
        Reject(),
    )

    return on_withdraw


def get_swap_program():
    on_swap_txn_index = Txn.group_index() - Int(1)
    given_token_amt_before_txn = ScratchVar(TealType.uint64)
    other_token_amt_before_txn = ScratchVar(TealType.uint64)

    to_send_key = ScratchVar(TealType.bytes)
    to_send_amount = ScratchVar(TealType.uint64)

    on_swap = Seq(
        token_a_holding,
        token_b_holding,
        Assert(
            And(
                App.globalGet(POOL_TOKENS_OUTSTANDING_KEY) > Int(0),
                Or(
                    validateTokenReceived(on_swap_txn_index, TOKEN_A_KEY),
                    validateTokenReceived(on_swap_txn_index, TOKEN_B_KEY),
                ),
            )
        ),
        If(Gtxn[on_swap_txn_index].xfer_asset() == App.globalGet(TOKEN_A_KEY))
        .Then(
            Seq(
                given_token_amt_before_txn.store(
                    token_a_holding.value() - Gtxn[on_swap_txn_index].asset_amount()
                ),
                other_token_amt_before_txn.store(token_b_holding.value()),
                to_send_key.store(TOKEN_B_KEY),
            )
        )
        .ElseIf(Gtxn[on_swap_txn_index].xfer_asset() == App.globalGet(TOKEN_B_KEY))
        .Then(
            Seq(
                given_token_amt_before_txn.store(
                    token_b_holding.value() - Gtxn[on_swap_txn_index].asset_amount()
                ),
                other_token_amt_before_txn.store(token_a_holding.value()),
                to_send_key.store(TOKEN_A_KEY),
            )
        )
        .Else(Reject()),
        to_send_amount.store(
            computeOtherTokenOutputPerGivenTokenInput(
                Gtxn[on_swap_txn_index].asset_amount(),
                given_token_amt_before_txn.load(),
                other_token_amt_before_txn.load(),
                App.globalGet(FEE_BPS_KEY),
            )
        ),
        Assert(
            And(
                to_send_amount.load() > Int(0),
                to_send_amount.load() < other_token_amt_before_txn.load(),
            )
        ),
        sendToken(to_send_key.load(), Txn.sender(), to_send_amount.load()),
        Approve(),
    )

    return on_swap


def approval_program():
    on_create = Seq(
        App.globalPut(CREATOR_KEY, Txn.application_args[0]),
        App.globalPut(TOKEN_A_KEY, Btoi(Txn.application_args[1])),
        App.globalPut(TOKEN_B_KEY, Btoi(Txn.application_args[2])),
        App.globalPut(FEE_BPS_KEY, Btoi(Txn.application_args[3])),
        App.globalPut(MIN_INCREMENT_KEY, Btoi(Txn.application_args[4])),
        Approve(),
    )

    on_setup = get_setup_program()
    on_supply = get_supply_program()
    on_withdraw = get_withdraw_program()
    on_swap = get_swap_program()

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("supply"), on_supply],
        [on_call_method == Bytes("withdraw"), on_withdraw],
        [on_call_method == Bytes("swap"), on_swap],
    )

    on_delete = Seq(
        If(App.globalGet(POOL_TOKENS_OUTSTANDING_KEY) == Int(0)).Then(
            Seq(Assert(Txn.sender() == App.globalGet(CREATOR_KEY)), Approve())
        ),
        Reject(),
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.NoOp, on_call],
        [Txn.on_completion() == OnComplete.DeleteApplication, on_delete],
        [
            Or(
                Txn.on_completion() == OnComplete.OptIn,
                Txn.on_completion() == OnComplete.CloseOut,
                Txn.on_completion() == OnComplete.UpdateApplication,
            ),
            Reject(),
        ],
    )

    return program


def clear_state_program():
    return Approve()



if __name__ == "__main__":
    with open("deposit_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=6)
        f.write(compiled)

    with open("deposit_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=6)
        f.write(compiled)