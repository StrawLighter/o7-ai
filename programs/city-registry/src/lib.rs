use anchor_lang::prelude::*;

declare_id!("5BQnx2X6gVmJ7WhQJ6vKCHHfdjkabR4oshVfQXukCCRg");

#[program]
pub mod city_registry {
    use super::*;

    pub fn register_agent(
        ctx: Context<RegisterAgent>,
        name: String,
        district: String,
    ) -> Result<()> {
        require!(name.len() <= 32, CityError::NameTooLong);
        require!(district.len() <= 32, CityError::DistrictTooLong);

        let agent = &mut ctx.accounts.agent;
        agent.owner = ctx.accounts.owner.key();
        agent.name = name.clone();
        agent.district = district;
        agent.brain_earned = 0;
        agent.brain_spent = 0;
        agent.tasks_completed = 0;
        agent.level = 1;
        agent.buildings = 0;
        agent.reputation = 0;

        msg!("Agent '{}' registered", name);
        Ok(())
    }

    pub fn update_agent_stats(
        ctx: Context<UpdateAgent>,
        brain_earned_delta: u64,
        brain_spent_delta: u64,
        tasks_completed_delta: u64,
    ) -> Result<()> {
        let agent = &mut ctx.accounts.agent;
        agent.brain_earned = agent.brain_earned.checked_add(brain_earned_delta).unwrap();
        agent.brain_spent = agent.brain_spent.checked_add(brain_spent_delta).unwrap();
        agent.tasks_completed = agent.tasks_completed.checked_add(tasks_completed_delta).unwrap();

        // Level up every 10 tasks
        agent.level = 1 + (agent.tasks_completed / 10) as u16;

        msg!("Agent stats updated — level {}", agent.level);
        Ok(())
    }

    pub fn place_building(
        ctx: Context<PlaceBuilding>,
        building_type: String,
        brain_cost: u64,
        grid_x: i16,
        grid_y: i16,
    ) -> Result<()> {
        require!(building_type.len() <= 32, CityError::BuildingTypeTooLong);

        let building = &mut ctx.accounts.building;
        building.owner = ctx.accounts.owner.key();
        building.building_type = building_type.clone();
        building.level = 1;
        building.brain_cost = brain_cost;
        building.output_multiplier = 100; // basis points, 100 = 1x
        building.grid_x = grid_x;
        building.grid_y = grid_y;

        let agent = &mut ctx.accounts.agent;
        agent.buildings = agent.buildings.checked_add(1).unwrap();

        msg!("Building '{}' placed at ({}, {})", building_type, grid_x, grid_y);
        Ok(())
    }
}

// ── Accounts ────────────────────────────────────────────────────────────────

#[derive(Accounts)]
#[instruction(name: String)]
pub struct RegisterAgent<'info> {
    #[account(mut)]
    pub owner: Signer<'info>,

    #[account(
        init,
        payer = owner,
        space = 8 + Agent::INIT_SPACE,
        seeds = [b"agent", owner.key().as_ref()],
        bump,
    )]
    pub agent: Account<'info, Agent>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateAgent<'info> {
    pub authority: Signer<'info>,

    #[account(
        mut,
        seeds = [b"agent", agent.owner.as_ref()],
        bump,
    )]
    pub agent: Account<'info, Agent>,
}

#[derive(Accounts)]
#[instruction(building_type: String, brain_cost: u64, grid_x: i16, grid_y: i16)]
pub struct PlaceBuilding<'info> {
    #[account(mut)]
    pub owner: Signer<'info>,

    #[account(
        mut,
        seeds = [b"agent", owner.key().as_ref()],
        bump,
    )]
    pub agent: Account<'info, Agent>,

    #[account(
        init,
        payer = owner,
        space = 8 + Building::INIT_SPACE,
        seeds = [b"building", owner.key().as_ref(), &grid_x.to_le_bytes(), &grid_y.to_le_bytes()],
        bump,
    )]
    pub building: Account<'info, Building>,

    pub system_program: Program<'info, System>,
}

// ── State ───────────────────────────────────────────────────────────────────

#[account]
#[derive(InitSpace)]
pub struct Agent {
    pub owner: Pubkey,
    #[max_len(32)]
    pub name: String,
    #[max_len(32)]
    pub district: String,
    pub brain_earned: u64,
    pub brain_spent: u64,
    pub tasks_completed: u64,
    pub level: u16,
    pub buildings: u32,
    pub reputation: u64,
}

#[account]
#[derive(InitSpace)]
pub struct Building {
    pub owner: Pubkey,
    #[max_len(32)]
    pub building_type: String,
    pub level: u16,
    pub brain_cost: u64,
    pub output_multiplier: u16,
    pub grid_x: i16,
    pub grid_y: i16,
}

// ── Errors ──────────────────────────────────────────────────────────────────

#[error_code]
pub enum CityError {
    #[msg("Name exceeds 32 characters")]
    NameTooLong,
    #[msg("District name exceeds 32 characters")]
    DistrictTooLong,
    #[msg("Building type exceeds 32 characters")]
    BuildingTypeTooLong,
}
