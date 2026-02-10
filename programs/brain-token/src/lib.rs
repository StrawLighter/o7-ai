use anchor_lang::prelude::*;
use anchor_spl::token::{self, Burn, Mint, MintTo, Token, TokenAccount};

declare_id!("3JJ5NNG5trMYsDoMXoAgvX3XFoFWnDagW16QyXRXdt8Z");

#[program]
pub mod brain_token {
    use super::*;

    pub fn initialize_brain(ctx: Context<InitializeBrain>, decimals: u8) -> Result<()> {
        let supply = &mut ctx.accounts.brain_supply;
        supply.authority = ctx.accounts.authority.key();
        supply.mint = ctx.accounts.mint.key();
        supply.total_minted = 0;
        supply.total_burned = 0;
        supply.decimals = decimals;
        msg!("BRAIN token initialized with {} decimals", decimals);
        Ok(())
    }

    pub fn mint_on_task_completion(
        ctx: Context<MintBrain>,
        amount: u64,
    ) -> Result<()> {
        let supply = &mut ctx.accounts.brain_supply;
        supply.total_minted = supply.total_minted.checked_add(amount).unwrap();

        let seeds = &[b"brain-mint-authority".as_ref(), &[ctx.bumps.mint_authority]];
        let signer_seeds = &[&seeds[..]];

        token::mint_to(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                MintTo {
                    mint: ctx.accounts.mint.to_account_info(),
                    to: ctx.accounts.recipient_ata.to_account_info(),
                    authority: ctx.accounts.mint_authority.to_account_info(),
                },
                signer_seeds,
            ),
            amount,
        )?;

        msg!("Minted {} BRAIN for task completion", amount);
        Ok(())
    }

    pub fn burn_on_api_call(ctx: Context<BurnBrain>, amount: u64) -> Result<()> {
        let supply = &mut ctx.accounts.brain_supply;
        supply.total_burned = supply.total_burned.checked_add(amount).unwrap();

        token::burn(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Burn {
                    mint: ctx.accounts.mint.to_account_info(),
                    from: ctx.accounts.burner_ata.to_account_info(),
                    authority: ctx.accounts.burner.to_account_info(),
                },
            ),
            amount,
        )?;

        msg!("Burned {} BRAIN for API call", amount);
        Ok(())
    }
}

// ── Accounts ────────────────────────────────────────────────────────────────

#[derive(Accounts)]
pub struct InitializeBrain<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(mut)]
    pub mint: Account<'info, Mint>,

    #[account(
        init,
        payer = authority,
        space = 8 + BrainSupply::INIT_SPACE,
        seeds = [b"brain-supply"],
        bump,
    )]
    pub brain_supply: Account<'info, BrainSupply>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct MintBrain<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(mut)]
    pub mint: Account<'info, Mint>,

    #[account(mut)]
    pub recipient_ata: Account<'info, TokenAccount>,

    /// CHECK: PDA used as mint authority
    #[account(
        seeds = [b"brain-mint-authority"],
        bump,
    )]
    pub mint_authority: UncheckedAccount<'info>,

    #[account(
        mut,
        seeds = [b"brain-supply"],
        bump,
    )]
    pub brain_supply: Account<'info, BrainSupply>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct BurnBrain<'info> {
    #[account(mut)]
    pub burner: Signer<'info>,

    #[account(mut)]
    pub mint: Account<'info, Mint>,

    #[account(mut)]
    pub burner_ata: Account<'info, TokenAccount>,

    #[account(
        mut,
        seeds = [b"brain-supply"],
        bump,
    )]
    pub brain_supply: Account<'info, BrainSupply>,

    pub token_program: Program<'info, Token>,
}

// ── State ───────────────────────────────────────────────────────────────────

#[account]
#[derive(InitSpace)]
pub struct BrainSupply {
    pub authority: Pubkey,
    pub mint: Pubkey,
    pub total_minted: u64,
    pub total_burned: u64,
    pub decimals: u8,
}
