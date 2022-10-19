// SPDX-License-Identifier: AGPL-3.0
pragma solidity 0.6.12;
pragma experimental ABIEncoderV2;

import "./interfaces/curve/Curve.sol";
import "./interfaces/lido/ISteth.sol";
import "./interfaces/UniswapInterfaces/IWETH.sol";


// These are the core Yearn libraries
import {
    BaseStrategy
} from "@yearnvaults/contracts/BaseStrategy.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/math/SafeMath.sol";
import "@openzeppelin/contracts/utils/Address.sol";
import "@openzeppelin/contracts/token/ERC20/SafeERC20.sol";
import "@openzeppelin/contracts/math/Math.sol";


// Import interfaces for many popular DeFi projects, or add your own!
//import "../interfaces/<protocol>/<Interface>.sol";

contract Strategy is BaseStrategy {
    using SafeERC20 for IERC20;
    using Address for address;
    using SafeMath for uint256;

    

    bool public checkLiqGauge = true;

    ICurveFi public constant StableSwapSTETH =  ICurveFi(0xDC24316b9AE028F1497c275EB9192a3Ea0f67022);
    IWETH public constant weth = IWETH(0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2);
    ISteth public constant stETH =  ISteth(0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84);
    
    address private referal = 0x16388463d60FFE0661Cf7F1f31a7D658aC790ff7; //stratms. for recycling and redepositing
    uint256 public maxSingleTrade;
    uint256 public constant DENOMINATOR = 10_000;
    uint256 public slippageProtectionOut;// = 50; //out of 10000. 50 = 0.5%

    bool public reportLoss = false;
    bool public dontInvest = false;

    uint256 public peg = 100; // 100 = 1%

    int128 private constant WETHID = 0;
    int128 private constant STETHID = 1;


    constructor(address _vault) public BaseStrategy(_vault) {
        // You can set these parameters on deployment to whatever you want
        maxReportDelay = 43200;
        profitFactor = 2000;
        debtThreshold = 400*1e18;

        stETH.approve(address(StableSwapSTETH), type(uint256).max);
        
        maxSingleTrade = 1_000 * 1e18;
        slippageProtectionOut = 500;
    }


    //we get eth
    receive() external payable {}

    function updateReferal(address _referal) external onlyEmergencyAuthorized {
        referal = _referal;
    }
    function updateMaxSingleTrade(uint256 _maxSingleTrade) external onlyVaultManagers {
        maxSingleTrade = _maxSingleTrade;
    }
    function updatePeg(uint256 _peg) external onlyVaultManagers {
        require(_peg <= 1_000); //limit peg to max 10%
        peg = _peg;
    }
    function updateReportLoss(bool _reportLoss) external onlyVaultManagers {
        reportLoss = _reportLoss;
    }
    function updateDontInvest(bool _dontInvest) external onlyVaultManagers {
        dontInvest = _dontInvest;
    }
    function updateSlippageProtectionOut(uint256 _slippageProtectionOut) external onlyVaultManagers {
        require(_slippageProtectionOut <= 10_000);
        slippageProtectionOut = _slippageProtectionOut;
    }
    
    function invest(uint256 _amount) external onlyEmergencyAuthorized{
        _invest(_amount);
    }

    //should never have stuck eth but just incase
    function rescueStuckEth() external onlyEmergencyAuthorized{
        weth.deposit{value: address(this).balance}();
    }


    function name() external override view returns (string memory) {
        // Add your own name here, suggestion e.g. "StrategyCreamYFI"
        return "StrategystETHAccumulator_v2";
    }

    // We hard code a peg here. This is so that we can build up a reserve of profit to cover peg volatility if we are forced to delever
    // This may sound scary but it is the equivalent of using virtualprice in a curve lp. As we have seen from many exploits, virtual pricing is safer than touch pricing.
    function estimatedTotalAssets() public override view returns (uint256) {
        return stethBalance().mul(DENOMINATOR.sub(peg)).div(DENOMINATOR).add(wantBalance());
    }

    function wantBalance() public view returns (uint256){
        return want.balanceOf(address(this));
    }
    function stethBalance() public view returns (uint256){
        return stETH.balanceOf(address(this));
    }

    function prepareReturn(uint256 _debtOutstanding)
        internal
        override
        returns (
            uint256 _profit,
            uint256 _loss,
            uint256 _debtPayment
        )
    {
        uint256 wantBal = wantBalance();
        uint256 totalAssets = estimatedTotalAssets();

        uint256 debt = vault.strategies(address(this)).totalDebt;

        if(totalAssets >= debt){
            _profit = totalAssets.sub(debt);

            uint256 toWithdraw = _profit.add(_debtOutstanding);

            if(toWithdraw > wantBal){
                uint256 willWithdraw = Math.min(maxSingleTrade, toWithdraw);
                uint256 withdrawn = _divest(willWithdraw); //we step our withdrawals. adjust max single trade to withdraw more
                if(withdrawn < willWithdraw){
                    _loss = willWithdraw.sub(withdrawn);
                }
                
            }
            wantBal = wantBalance();

            //net off profit and loss
            if(_profit >= _loss){
                _profit = _profit - _loss;
                _loss = 0;
            }else{
                _profit = 0;
                _loss = _loss - _profit;
            }

            //profit + _debtOutstanding must be <= wantbalance. Prioritise profit first
            if(wantBal < _profit){
                _profit = wantBal;
            }else if(wantBal < toWithdraw){
                _debtPayment = wantBal.sub(_profit);
            }else{
                _debtPayment = _debtOutstanding;
            }

        }else{
            if(reportLoss){
                _loss = debt.sub(totalAssets);
            }
            
        }
        
    }

    function ethToWant(uint256 _amtInWei) public view override returns (uint256){
        return _amtInWei;
    }
    function liquidateAllPositions() internal override returns (uint256 _amountFreed){
        _divest(stethBalance());
        _amountFreed = wantBalance();
    }

    function adjustPosition(uint256 _debtOutstanding) internal override {
        
        if(dontInvest){
            return;
        }
        _invest(wantBalance());
    }

    function _invest(uint256 _amount) internal returns (uint256){
        if(_amount == 0){
            return 0;
        }

        _amount = Math.min(maxSingleTrade, _amount);
        uint256 before = stethBalance();

        weth.withdraw(_amount);

        //test if we should buy instead of mint
        uint256 out = StableSwapSTETH.get_dy(WETHID, STETHID, _amount);
        if(out < _amount){
           stETH.submit{value: _amount}(referal);
        }else{        
            StableSwapSTETH.exchange{value: _amount}(WETHID, STETHID, _amount, _amount);
        }

        return stethBalance().sub(before);
    }

    function _divest(uint256 _amount) internal returns (uint256){
        uint256 before = wantBalance();

        uint256 slippageAllowance = _amount.mul(DENOMINATOR.sub(slippageProtectionOut)).div(DENOMINATOR);
        StableSwapSTETH.exchange(STETHID, WETHID, _amount,slippageAllowance);

        weth.deposit{value: address(this).balance}();

        return wantBalance().sub(before);
    }


    // we attempt to withdraw the full amount and let the user decide if they take the loss or not
    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        uint256 wantBal = wantBalance();
        if(wantBal < _amountNeeded){
            uint256 toWithdraw = _amountNeeded.sub(wantBal);
            uint256 withdrawn = _divest(toWithdraw);
            if(withdrawn < toWithdraw){
                _loss = toWithdraw.sub(withdrawn);
            }
        }
    
        _liquidatedAmount = _amountNeeded.sub(_loss);
    }

    // NOTE: Can override `tendTrigger` and `harvestTrigger` if necessary

    function prepareMigration(address _newStrategy) internal override {
        uint256 stethBal = stethBalance();
        if (stethBal > 0) {
            stETH.transfer(_newStrategy, stethBal);
        }
    }


    // Override this to add all tokens/tokenized positions this contract manages
    // on a *persistent* basis (e.g. not just for swapping back to want ephemerally)
    // NOTE: Do *not* include `want`, already included in `sweep` below
    //
    // Example:
    //
    //    function protectedTokens() internal override view returns (address[] memory) {
    //      address[] memory protected = new address[](3);
    //      protected[0] = tokenA;
    //      protected[1] = tokenB;
    //      protected[2] = tokenC;
    //      return protected;
    //    }
    function protectedTokens()
        internal
        override
        view
        returns (address[] memory)
    {
    }
}
