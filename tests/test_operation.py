from itertools import count
from brownie import Wei, reverts
import eth_abi
from brownie.convert import to_bytes
from useful_methods import genericStateOfStrat,genericStateOfVault
import random
import brownie
from pytest import approx

# TODO: Add tests here that show the normal operation of this strategy
#       Suggestions to include:
#           - strategy loading and unloading (via Vault addStrategy/revokeStrategy)
#           - change in loading (from low to high and high to low)
#           - strategy operation at different loading levels (anticipated and "extreme")

def test_profitable_harvest(currency,strategy,Contract, chain,vault, steth, whale,gov,strategist, steth_holder, interface):
    rate_limit = 2**256 -1
    debt_ratio = 10_000
    weth = currency
    vault.addStrategy(strategy, debt_ratio, 0,rate_limit, 1000, {"from": gov})
    strategy.updatePeg(0, {'from':gov})

    currency.approve(vault, 2 ** 256 - 1, {"from": whale} )
    whalebefore = currency.balanceOf(whale)
    whale_deposit  = 100 *1e18
    vault.deposit(whale_deposit, {"from": whale})
    strategy.harvest({'from': strategist})
    assert weth.balanceOf(strategy) == 0
    assert steth.balanceOf(strategy) >= whale_deposit

    #genericStateOfStrat(strategy, currency, vault)
    #genericStateOfVault(vault, currency)

    days = 14
    chain.sleep(days*24*60*60)
    chain.mine(1)

    #send some steth to simulate profit. 10% apr
    rewards_amount = whale_deposit/10/365*days
    steth.transfer(strategy, rewards_amount, {'from': steth_holder})

    #genericStateOfStrat(strategy, currency, vault)
    #genericStateOfVault(vault, currency)


    strategy.harvest({'from': strategist})

    assert steth.balanceOf(strategy) >= whale_deposit #only profit sent
    assert weth.balanceOf(vault) >= rewards_amount * 0.995 # 0.5% max slippage
    assert strategy.balance() == 0

    vault.updateStrategyDebtRatio(strategy, 0, {'from': gov})
    chain.sleep(1)#make sure we're not on same timestamp which causes revert in assessFees

    #revert because we have loss
    with brownie.reverts("!healthcheck"):
        strategy.harvest({'from': strategist})
    strategy.setDoHealthCheck(False, {'from': gov})
    strategy.harvest({'from': strategist})

    assert steth.balanceOf(strategy) <= 1 #no balance left
    assert weth.balanceOf(vault) >= (rewards_amount + whale_deposit) * 0.995 # 0.5% max slippage
    assert strategy.balance() == 0

    #genericStateOfStrat(strategy, currency, vault)
    #genericStateOfVault(vault, currency)

    
    vault.withdraw({"from": whale})
    whale_profit = (currency.balanceOf(whale) - whalebefore)/1e18
    print("Whale profit: ", whale_profit)
    assert whale_profit > 0

def test_deep_withdrawal(currency,strategy,Contract, chain,vault, nocoiner, steth, whale,gov,strategist, steth_holder, interface):
    rate_limit = 2**256 -1
    debt_ratio = 10_000
    weth = currency
    strategy.updatePeg(0, {'from':gov})
    vault.addStrategy(strategy, debt_ratio, 0,rate_limit, 1000, {"from": gov})
    gov.transfer(strategy, 1*1e14)
    
    with brownie.reverts():
        strategy.rescueStuckEth({"from": nocoiner})

    strategy.rescueStuckEth({"from": gov})

    currency.approve(vault, 2 ** 256 - 1, {"from": whale} )
    whalebefore = currency.balanceOf(whale)
    whale_deposit  = 100 *1e18
    vault.deposit(whale_deposit, {"from": whale})
    strategy.harvest({'from': strategist})

    with brownie.reverts():
        vault.withdraw({"from": whale})
    
    vault.withdraw(vault.balanceOf(whale),whale, 500, {"from": whale})
    
    whale_profit = (currency.balanceOf(whale) - whalebefore)/1e18
    print("Whale profit: ", whale_profit)
    assert whale_profit > -1 * whale_deposit * 0.01

def test_emergency_exit(currency,strategy,Contract, chain,vault, steth, whale,gov,strategist, steth_holder, interface):
    rate_limit = 2**256 -1
    debt_ratio = 10_000
    # strategy.updatePeg(0, {'from':gov})
    weth = currency
    vault.addStrategy(strategy, debt_ratio, 0,rate_limit, 1000, {"from": gov})

    currency.approve(vault, 2 ** 256 - 1, {"from": whale} )
    whalebefore = currency.balanceOf(whale)
    whale_deposit  = 100 *1e18
    vault.deposit(whale_deposit, {"from": whale})
    strategy.harvest({'from': strategist})
    assert weth.balanceOf(strategy) == 0
    assert steth.balanceOf(strategy) >= whale_deposit
    strategy.setDoHealthCheck(False, {'from': gov})
    strategy.setEmergencyExit({'from': gov})

    chain.sleep(1)
    strategy.harvest({'from': strategist})


    assert steth.balanceOf(strategy) <= 1
    assert strategy.estimatedTotalAssets() <= 1
    assert weth.balanceOf(vault) >= whale_deposit * 0.99 # 0.5% max slippage in both directions


def test_migrate(currency,strategy,Strategy, Contract, chain,vault, steth, whale,gov,strategist, steth_holder, interface):
    rate_limit = 2**256 -1
    debt_ratio = 10_000
    weth = currency
    vault.addStrategy(strategy, debt_ratio, 0,rate_limit, 1000, {"from": gov})

    currency.approve(vault, 2 ** 256 - 1, {"from": whale} )
    whale_deposit  = 100 *1e18
    vault.deposit(whale_deposit, {"from": whale})
    strategy.harvest({'from': strategist})
    before_steth = steth.balanceOf(strategy)
    assert before_steth >= whale_deposit

    strategy2 = strategist.deploy(Strategy, vault)
    vault.migrateStrategy(strategy, strategy2, {'from': gov})

    #we can be left with some dust due to roudning errors in steth converting shares
    assert steth.balanceOf(strategy2) >= before_steth-1 and steth.balanceOf(strategy2) <= before_steth + 1
    assert strategy.estimatedTotalAssets() <= 1




def test_massive_deposit(currency,Strategy, steth,strategy, chain,vault, whale,gov,strategist, interface):
    rate_limit = 1_000_000_000 *1e18
    debt_ratio = 10_000
    vault.addStrategy(strategy, debt_ratio, 0, rate_limit, 1000, {"from": gov})
    strategy.updateMaxSingleTrade(150_000*1e18, {"from": gov})

    currency.approve(vault, 2 ** 256 - 1, {"from": whale} )
    whale_deposit  = 150_000 *1e18
    vault.deposit(whale_deposit, {"from": whale})
    eth_staker_balance = steth.balance()
    strategy.harvest({'from': strategist})

    #make sure we take the staking route
    assert (steth.balance() - eth_staker_balance) == whale_deposit
    #assert len(tx.events['Submitted'] == 1)

    #genericStateOfStrat(strategy, currency, vault)
    #genericStateOfVault(vault, currency)

    assert currency.balanceOf(strategy) == 0
    assert steth.balanceOf(strategy)/1e18 >= (whale_deposit-1)/1e18


def test_multiple_step_deposit(currency,strategy,Contract, chain,vault, steth, whale,gov,strategist, steth_holder, interface):
    rate_limit = 2**256 -1
    debt_ratio = 10_000
    weth = currency
    vault.addStrategy(strategy, debt_ratio, 0,rate_limit, 1000, {"from": gov})

    currency.approve(vault, 2 ** 256 - 1, {"from": whale} )
    whalebefore = currency.balanceOf(whale)
    whale_deposit  = 3_000 *1e18
    max =  strategy.maxSingleTrade() 
    assert max/1e18 == 1_000

    vault.deposit(whale_deposit, {"from": whale})
    strategy.harvest({'from': strategist})
    assert approx(weth.balanceOf(strategy), 1) == whale_deposit - max
    assert steth.balanceOf(strategy) >= max

    strategy.invest(weth.balanceOf(strategy) , {'from': strategist})

    assert weth.balanceOf(strategy) == whale_deposit - (max*2)
    assert steth.balanceOf(strategy) >= max*2

    chain.sleep(1)
    strategy.harvest({'from': strategist})
    assert weth.balanceOf(strategy) == 0
    
def test_multiple_step_withdrawal(currency,strategy,Contract, chain,vault, steth, whale,gov,strategist, steth_holder, interface):
    rate_limit = 2**256 -1
    debt_ratio = 10_000
    strategy.updatePeg(0, {'from':gov})
    weth = currency
    vault.addStrategy(strategy, debt_ratio, 0,rate_limit, 1000, {"from": gov})
    strategy.updateMaxSingleTrade(500_000*1e18, {"from": gov})

    currency.approve(vault, 2 ** 256 - 1, {"from": whale} )
    whalebefore = currency.balanceOf(whale)
    whale_deposit  = 3_000 *1e18

    vault.deposit(whale_deposit, {"from": whale})
    strategy.harvest({'from': strategist})
    assert weth.balanceOf(strategy) == 0

    single_trade = 1_000*1e18
    strategy.updateMaxSingleTrade(single_trade, {"from": gov})
    vault.updateStrategyDebtRatio(strategy, 0, {'from': gov})
    strategy.setDoHealthCheck(False, {'from': gov})

    chain.sleep(1)
    strategy.harvest({'from': strategist})
    assert strategy.estimatedTotalAssets() >= whale_deposit - single_trade
    assert weth.balanceOf(vault) >= single_trade * 0.995
    strategy.setDoHealthCheck(False, {'from': gov})
    chain.sleep(1)
    strategy.harvest({'from': strategist})
    strategy.setDoHealthCheck(False, {'from': gov})
    chain.sleep(1)
    strategy.harvest({'from': strategist})
    assert strategy.estimatedTotalAssets() < single_trade
    assert weth.balanceOf(vault) >= single_trade *3 * 0.995
    genericStateOfStrat(strategy, currency, vault)
    genericStateOfVault(vault, currency)

def test_updates(currency,strategy,Contract, chain,vault, steth, whale,gov,strategist, steth_holder, interface):
    
    with brownie.reverts():
        strategy.updateReferal(whale, {'from': whale})

    with brownie.reverts():
        strategy.updateMaxSingleTrade(1, {'from': whale})
    
    with brownie.reverts():
        strategy.updateSlippageProtectionOut(1, {'from': whale})

    with brownie.reverts():
        strategy.updatePeg(1, {'from': whale})
    
    with brownie.reverts():
        strategy.updateReportLoss(True, {'from': whale})
    
    with brownie.reverts():
        strategy.updateDontInvest(True, {'from': whale})

    with brownie.reverts():
        strategy.setKeeper(whale, {'from': whale})

    strategy.updateSlippageProtectionOut(1, {'from': gov})
    strategy.updateMaxSingleTrade(1, {'from': gov})
    strategy.updateReferal(whale, {'from': gov})