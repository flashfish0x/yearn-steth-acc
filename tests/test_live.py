from itertools import count
from threading import activeCount
from brownie import Wei, reverts
import eth_abi
from brownie.convert import to_bytes
from useful_methods import genericStateOfStrat,genericStateOfVault
import random
import brownie

# TODO: Add tests here that show the normal operation of this strategy
#       Suggestions to include:
#           - strategy loading and unloading (via Vault addStrategy/revokeStrategy)
#           - change in loading (from low to high and high to low)
#           - strategy operation at different loading levels (anticipated and "extreme")

def test_migrate_live(currency,live_strategy, Strategy, chain,live_vault, whale, samdev,strategist, interface, accounts):
    
    gov = accounts.at(live_vault.governance(), force='True')
    before = live_strategy.estimatedTotalAssets()
    strategy = strategist.deploy(Strategy, live_vault)

    live_vault.migrateStrategy(live_strategy, strategy, {'from': gov})

    after = strategy.estimatedTotalAssets()

    assert after == (before * (10_000 - 100)) // 10_000 -1

    t1 = strategy.harvest({'from': gov})
    print(t1.events['Harvested'])

    strategy.updatePeg(0, {'from': gov})
    strategy.updateMaxSingleTrade(2**256-1, {'from': gov})
    live_vault.updateStrategyDebtRatio(strategy, 0, {'from': gov})
    t1 = strategy.harvest({'from': gov})
    print(t1.events['Harvested'])
    assert strategy.wantBalance() <= 1
    assert strategy.stethBalance() <= 1
