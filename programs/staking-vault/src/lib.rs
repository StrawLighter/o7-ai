use anchor_lang::prelude::*;
use anchor_lang::system_program;

declare_id!("CdTaBicv2ppsi8y9YxACvb73qsT2r3A12c26tDTH2unS");

#[program]
pub mod staking_vault {
    use super::*;

    pub fn initialize_vault(ctx: Context<InitializeVault>) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        vault.authority = ctx.accounts.authority.key();
        vault.total_sol_deposited = 0;
        vault.total_sol_withdrawn = 0;
        vault.lst_delegated = 0;
        vault.brain_yield_distributed = 0;
        vault.staker_count = 0;

        msg!("Staking vault initialized");
        Ok(())
    }

    pub fn stake_sol(ctx: Context<StakeSol>, amount: u64) -> Result<()> {
        require!(amount > 0, VaultError::ZeroAmount);

        // Transfer SOL from staker to vault PDA
        system_program::transfer(
            CpiContext::new(
                ctx.accounts.system_program.to_account_info(),
                system_program::Transfer {
                    from: ctx.accounts.staker.to_account_info(),
                    to: ctx.accounts.vault_sol.to_account_info(),
                },
            ),
            amount,
        )?;

        let stake_receipt = &mut ctx.accounts.stake_receipt;
        if stake_receipt.staker == Pubkey::default() {
            // New staker
            stake_receipt.staker = ctx.accounts.staker.key();
            stake_receipt.sol_deposited = amount;
            stake_receipt.lst_share = 0;
            stake_receipt.brain_claimed = 0;
            stake_receipt.deposit_ts = Clock::get()?.unix_timestamp;

            let vault = &mut ctx.accounts.vault;
            vault.staker_count = vault.staker_count.checked_add(1).unwrap();
        } else {
            stake_receipt.sol_deposited = stake_receipt.sol_deposited.checked_add(amount).unwrap();
        }

        let vault = &mut ctx.accounts.vault;
        vault.total_sol_deposited = vault.total_sol_deposited.checked_add(amount).unwrap();

        msg!("Staked {} lamports", amount);
        Ok(())
    }

    pub fn record_lst_delegation(
        ctx: Context<AdminAction>,
        amount: u64,
    ) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        vault.lst_delegated = vault.lst_delegated.checked_add(amount).unwrap();
        msg!("Recorded {} LST delegation", amount);
        Ok(())
    }

    pub fn distribute_brain_yield(
        ctx: Context<AdminAction>,
        amount: u64,
    ) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        vault.brain_yield_distributed = vault
            .brain_yield_distributed
            .checked_add(amount)
            .unwrap();
        msg!("Distributed {} BRAIN yield to treasury", amount);
        Ok(())
    }
}

// ── Accounts ────────────────────────────────────────────────────────────────

#[derive(Accounts)]
pub struct InitializeVault<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        init,
        payer = authority,
        space = 8 + Vault::INIT_SPACE,
        seeds = [b"vault"],
        bump,
    )]
    pub vault: Account<'info, Vault>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct StakeSol<'info> {
    #[account(mut)]
    pub staker: Signer<'info>,

    #[account(
        mut,
        seeds = [b"vault"],
        bump,
    )]
    pub vault: Account<'info, Vault>,

    /// CHECK: PDA that holds SOL deposits
    #[account(
        mut,
        seeds = [b"vault-sol"],
        bump,
    )]
    pub vault_sol: UncheckedAccount<'info>,

    #[account(
        init_if_needed,
        payer = staker,
        space = 8 + StakeReceipt::INIT_SPACE,
        seeds = [b"stake", staker.key().as_ref()],
        bump,
    )]
    pub stake_receipt: Account<'info, StakeReceipt>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct AdminAction<'info> {
    pub authority: Signer<'info>,

    #[account(
        mut,
        seeds = [b"vault"],
        bump,
        has_one = authority,
    )]
    pub vault: Account<'info, Vault>,
}

// ── State ───────────────────────────────────────────────────────────────────

#[account]
#[derive(InitSpace)]
pub struct Vault {
    pub authority: Pubkey,
    pub total_sol_deposited: u64,
    pub total_sol_withdrawn: u64,
    pub lst_delegated: u64,
    pub brain_yield_distributed: u64,
    pub staker_count: u32,
}

#[account]
#[derive(InitSpace)]
pub struct StakeReceipt {
    pub staker: Pubkey,
    pub sol_deposited: u64,
    pub lst_share: u64,
    pub brain_claimed: u64,
    pub deposit_ts: i64,
}

// ── Errors ──────────────────────────────────────────────────────────────────

#[error_code]
pub enum VaultError {
    #[msg("Amount must be greater than zero")]
    ZeroAmount,
}
