use anchor_lang::prelude::*;

declare_id!("5nnAtvyXk388f3SwQXihxiGxfyPQzy9U3dzPohvkH9fY");

#[program]
pub mod task_marketplace {
    use super::*;

    pub fn create_task(
        ctx: Context<CreateTask>,
        task_id: u64,
        task_type: TaskType,
        description: String,
        reward_brain: u64,
    ) -> Result<()> {
        require!(description.len() <= 256, TaskError::DescriptionTooLong);

        let task = &mut ctx.accounts.task;
        task.id = task_id;
        task.creator = ctx.accounts.creator.key();
        task.task_type = task_type;
        task.description = description;
        task.reward_brain = reward_brain;
        task.assigned_agent = Pubkey::default();
        task.status = TaskStatus::Open;
        task.result_uri = String::new();

        msg!("Task {} created — reward: {} BRAIN", task_id, reward_brain);
        Ok(())
    }

    pub fn assign_task(ctx: Context<AssignTask>, agent: Pubkey) -> Result<()> {
        let task = &mut ctx.accounts.task;
        require!(task.status == TaskStatus::Open, TaskError::NotOpen);

        task.assigned_agent = agent;
        task.status = TaskStatus::InProgress;

        msg!("Task {} assigned to {}", task.id, agent);
        Ok(())
    }

    pub fn submit_result(ctx: Context<SubmitResult>, result_uri: String) -> Result<()> {
        require!(result_uri.len() <= 256, TaskError::UriTooLong);

        let task = &mut ctx.accounts.task;
        require!(task.status == TaskStatus::InProgress, TaskError::NotInProgress);
        require!(
            task.assigned_agent == ctx.accounts.agent.key(),
            TaskError::NotAssignedAgent
        );

        task.result_uri = result_uri;
        task.status = TaskStatus::Completed;

        msg!("Task {} result submitted", task.id);
        Ok(())
    }

    pub fn verify_task(ctx: Context<VerifyTask>) -> Result<()> {
        let task = &mut ctx.accounts.task;
        require!(task.status == TaskStatus::Completed, TaskError::NotCompleted);
        require!(
            task.creator == ctx.accounts.creator.key(),
            TaskError::NotCreator
        );

        task.status = TaskStatus::Verified;
        msg!("Task {} verified", task.id);
        Ok(())
    }
}

// ── Accounts ────────────────────────────────────────────────────────────────

#[derive(Accounts)]
#[instruction(task_id: u64)]
pub struct CreateTask<'info> {
    #[account(mut)]
    pub creator: Signer<'info>,

    #[account(
        init,
        payer = creator,
        space = 8 + Task::INIT_SPACE,
        seeds = [b"task", task_id.to_le_bytes().as_ref()],
        bump,
    )]
    pub task: Account<'info, Task>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct AssignTask<'info> {
    pub creator: Signer<'info>,

    #[account(
        mut,
        has_one = creator,
    )]
    pub task: Account<'info, Task>,
}

#[derive(Accounts)]
pub struct SubmitResult<'info> {
    pub agent: Signer<'info>,

    #[account(mut)]
    pub task: Account<'info, Task>,
}

#[derive(Accounts)]
pub struct VerifyTask<'info> {
    pub creator: Signer<'info>,

    #[account(
        mut,
        has_one = creator,
    )]
    pub task: Account<'info, Task>,
}

// ── State ───────────────────────────────────────────────────────────────────

#[account]
#[derive(InitSpace)]
pub struct Task {
    pub id: u64,
    pub creator: Pubkey,
    pub task_type: TaskType,
    #[max_len(256)]
    pub description: String,
    pub reward_brain: u64,
    pub assigned_agent: Pubkey,
    pub status: TaskStatus,
    #[max_len(256)]
    pub result_uri: String,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum TaskType {
    Script,
    Voiceover,
    Copy,
    Ugc,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum TaskStatus {
    Open,
    InProgress,
    Completed,
    Verified,
}

// ── Errors ──────────────────────────────────────────────────────────────────

#[error_code]
pub enum TaskError {
    #[msg("Description exceeds 256 characters")]
    DescriptionTooLong,
    #[msg("Result URI exceeds 256 characters")]
    UriTooLong,
    #[msg("Task is not open")]
    NotOpen,
    #[msg("Task is not in progress")]
    NotInProgress,
    #[msg("Task is not completed")]
    NotCompleted,
    #[msg("Signer is not the assigned agent")]
    NotAssignedAgent,
    #[msg("Signer is not the task creator")]
    NotCreator,
}
