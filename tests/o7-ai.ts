import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { BrainToken } from "../target/types/brain_token";
import { CityRegistry } from "../target/types/city_registry";
import { TaskMarketplace } from "../target/types/task_marketplace";
import { StakingVault } from "../target/types/staking_vault";
import {
  createMint,
  getOrCreateAssociatedTokenAccount,
  getAccount,
} from "@solana/spl-token";
import { PublicKey, Keypair, SystemProgram } from "@solana/web3.js";
import { assert } from "chai";
import BN from "bn.js";

describe("o7-ai full demo loop", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const brainToken = anchor.workspace.brainToken as Program<BrainToken>;
  const cityRegistry = anchor.workspace.cityRegistry as Program<CityRegistry>;
  const taskMarketplace = anchor.workspace
    .taskMarketplace as Program<TaskMarketplace>;
  const stakingVault = anchor.workspace.stakingVault as Program<StakingVault>;

  const authority = provider.wallet as anchor.Wallet;

  // We'll use a separate keypair to simulate the "agent" role
  const agentKeypair = Keypair.generate();

  let brainMint: PublicKey;
  let mintAuthorityPda: PublicKey;
  let mintAuthorityBump: number;
  let brainSupplyPda: PublicKey;
  let authorityAta: any;
  let agentAta: any;
  let agentPda: PublicKey;
  let taskPda: PublicKey;

  const BRAIN_DECIMALS = 9;
  const TASK_ID = new BN(1);
  const REWARD_AMOUNT = new BN(100_000_000_000); // 100 BRAIN (9 decimals)
  const BURN_AMOUNT = new BN(10_000_000_000); // 10 BRAIN

  before("Fund the agent wallet", async () => {
    // Transfer some SOL to the agent so it can sign transactions
    const tx = new anchor.web3.Transaction().add(
      SystemProgram.transfer({
        fromPubkey: authority.publicKey,
        toPubkey: agentKeypair.publicKey,
        lamports: 100_000_000, // 0.1 SOL
      })
    );
    await provider.sendAndConfirm(tx);
    console.log(
      `  Agent funded: ${agentKeypair.publicKey.toBase58()} with 0.1 SOL`
    );
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 1: Initialize BRAIN mint
  // ═══════════════════════════════════════════════════════════════════════════
  it("1. Initialize BRAIN token mint", async () => {
    // Derive the PDA that will be the mint authority
    [mintAuthorityPda, mintAuthorityBump] = PublicKey.findProgramAddressSync(
      [Buffer.from("brain-mint-authority")],
      brainToken.programId
    );

    [brainSupplyPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("brain-supply")],
      brainToken.programId
    );

    // Create the SPL token mint with mintAuthorityPda as the authority
    brainMint = await createMint(
      provider.connection,
      (authority as any).payer,
      mintAuthorityPda, // mint authority is the PDA
      null, // no freeze authority
      BRAIN_DECIMALS
    );
    console.log(`  BRAIN mint: ${brainMint.toBase58()}`);

    // Initialize the brain supply tracker
    const tx = await brainToken.methods
      .initializeBrain(BRAIN_DECIMALS)
      .accounts({
        authority: authority.publicKey,
        mint: brainMint,
        brainSupply: brainSupplyPda,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    console.log(`  initializeBrain tx: ${tx}`);

    // Verify
    const supply = await brainToken.account.brainSupply.fetch(brainSupplyPda);
    assert.ok(supply.authority.equals(authority.publicKey));
    assert.ok(supply.mint.equals(brainMint));
    assert.equal(supply.totalMinted.toNumber(), 0);
    assert.equal(supply.totalBurned.toNumber(), 0);
    assert.equal(supply.decimals, BRAIN_DECIMALS);
    console.log("  ✓ BrainSupply account initialized");
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 2: Register an agent in the city
  // ═══════════════════════════════════════════════════════════════════════════
  it("2. Register an agent", async () => {
    [agentPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("agent"), authority.publicKey.toBuffer()],
      cityRegistry.programId
    );

    const tx = await cityRegistry.methods
      .registerAgent("AgentSmith", "Downtown")
      .accounts({
        owner: authority.publicKey,
        agent: agentPda,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    console.log(`  registerAgent tx: ${tx}`);

    const agent = await cityRegistry.account.agent.fetch(agentPda);
    assert.equal(agent.name, "AgentSmith");
    assert.equal(agent.district, "Downtown");
    assert.equal(agent.level, 1);
    assert.equal(agent.tasksCompleted.toNumber(), 0);
    assert.equal(agent.brainEarned.toNumber(), 0);
    console.log(
      `  ✓ Agent registered: ${agent.name} in ${agent.district}, level ${agent.level}`
    );
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 3: Create a Script task with 100 BRAIN reward
  // ═══════════════════════════════════════════════════════════════════════════
  it("3. Create a Script task with 100 BRAIN reward", async () => {
    [taskPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("task"), TASK_ID.toArrayLike(Buffer, "le", 8)],
      taskMarketplace.programId
    );

    const tx = await taskMarketplace.methods
      .createTask(
        TASK_ID,
        { script: {} },
        "Write a 60s TikTok script about AI agents",
        REWARD_AMOUNT
      )
      .accounts({
        creator: authority.publicKey,
        task: taskPda,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    console.log(`  createTask tx: ${tx}`);

    const task = await taskMarketplace.account.task.fetch(taskPda);
    assert.equal(task.id.toNumber(), 1);
    assert.deepEqual(task.taskType, { script: {} });
    assert.equal(
      task.description,
      "Write a 60s TikTok script about AI agents"
    );
    assert.equal(task.rewardBrain.toNumber(), REWARD_AMOUNT.toNumber());
    assert.deepEqual(task.status, { open: {} });
    console.log(
      `  ✓ Task created: id=${task.id}, type=Script, reward=${
        task.rewardBrain.toNumber() / 1e9
      } BRAIN, status=Open`
    );
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 4: Assign task to the agent
  // ═══════════════════════════════════════════════════════════════════════════
  it("4. Assign task to agent", async () => {
    const tx = await taskMarketplace.methods
      .assignTask(agentKeypair.publicKey)
      .accounts({
        creator: authority.publicKey,
        task: taskPda,
      })
      .rpc();
    console.log(`  assignTask tx: ${tx}`);

    const task = await taskMarketplace.account.task.fetch(taskPda);
    assert.ok(task.assignedAgent.equals(agentKeypair.publicKey));
    assert.deepEqual(task.status, { inProgress: {} });
    console.log(
      `  ✓ Task assigned to ${agentKeypair.publicKey
        .toBase58()
        .slice(0, 8)}..., status=InProgress`
    );
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 5: Agent submits a mock result URI
  // ═══════════════════════════════════════════════════════════════════════════
  it("5. Agent submits result", async () => {
    const resultUri = "https://arweave.net/mock-result-hash-abc123";

    const tx = await taskMarketplace.methods
      .submitResult(resultUri)
      .accounts({
        agent: agentKeypair.publicKey,
        task: taskPda,
      })
      .signers([agentKeypair])
      .rpc();
    console.log(`  submitResult tx: ${tx}`);

    const task = await taskMarketplace.account.task.fetch(taskPda);
    assert.equal(task.resultUri, resultUri);
    assert.deepEqual(task.status, { completed: {} });
    console.log(
      `  ✓ Result submitted: ${task.resultUri}, status=Completed`
    );
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 6: Creator verifies the task
  // ═══════════════════════════════════════════════════════════════════════════
  it("6. Creator verifies task", async () => {
    const tx = await taskMarketplace.methods
      .verifyTask()
      .accounts({
        creator: authority.publicKey,
        task: taskPda,
      })
      .rpc();
    console.log(`  verifyTask tx: ${tx}`);

    const task = await taskMarketplace.account.task.fetch(taskPda);
    assert.deepEqual(task.status, { verified: {} });
    console.log("  ✓ Task verified, status=Verified");
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 7: Mint 100 BRAIN to the agent as reward
  // ═══════════════════════════════════════════════════════════════════════════
  it("7. Mint BRAIN to agent on task completion", async () => {
    // Create ATA for the agent
    agentAta = await getOrCreateAssociatedTokenAccount(
      provider.connection,
      (authority as any).payer,
      brainMint,
      agentKeypair.publicKey
    );

    const tx = await brainToken.methods
      .mintOnTaskCompletion(REWARD_AMOUNT)
      .accounts({
        authority: authority.publicKey,
        mint: brainMint,
        recipientAta: agentAta.address,
        mintAuthority: mintAuthorityPda,
        brainSupply: brainSupplyPda,
        tokenProgram: anchor.utils.token.TOKEN_PROGRAM_ID,
      })
      .rpc();
    console.log(`  mintOnTaskCompletion tx: ${tx}`);

    // Verify token balance
    const ataInfo = await getAccount(provider.connection, agentAta.address);
    assert.equal(ataInfo.amount.toString(), REWARD_AMOUNT.toString());

    // Verify supply tracker
    const supply = await brainToken.account.brainSupply.fetch(brainSupplyPda);
    assert.equal(supply.totalMinted.toNumber(), REWARD_AMOUNT.toNumber());
    console.log(
      `  ✓ Minted ${
        REWARD_AMOUNT.toNumber() / 1e9
      } BRAIN to agent — total minted: ${supply.totalMinted.toNumber() / 1e9}`
    );
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // STEP 8: Agent burns BRAIN to simulate an API call
  // ═══════════════════════════════════════════════════════════════════════════
  it("8. Agent burns BRAIN to simulate API call", async () => {
    const tx = await brainToken.methods
      .burnOnApiCall(BURN_AMOUNT)
      .accounts({
        burner: agentKeypair.publicKey,
        mint: brainMint,
        burnerAta: agentAta.address,
        brainSupply: brainSupplyPda,
        tokenProgram: anchor.utils.token.TOKEN_PROGRAM_ID,
      })
      .signers([agentKeypair])
      .rpc();
    console.log(`  burnOnApiCall tx: ${tx}`);

    // Verify remaining balance
    const ataInfo = await getAccount(provider.connection, agentAta.address);
    const expectedRemaining = REWARD_AMOUNT.sub(BURN_AMOUNT);
    assert.equal(ataInfo.amount.toString(), expectedRemaining.toString());

    // Verify supply tracker
    const supply = await brainToken.account.brainSupply.fetch(brainSupplyPda);
    assert.equal(supply.totalBurned.toNumber(), BURN_AMOUNT.toNumber());
    console.log(
      `  ✓ Burned ${BURN_AMOUNT.toNumber() / 1e9} BRAIN — remaining: ${
        Number(ataInfo.amount) / 1e9
      }, total burned: ${supply.totalBurned.toNumber() / 1e9}`
    );
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // SUMMARY: Print final state
  // ═══════════════════════════════════════════════════════════════════════════
  it("9. Final state summary", async () => {
    const supply = await brainToken.account.brainSupply.fetch(brainSupplyPda);
    const agent = await cityRegistry.account.agent.fetch(agentPda);
    const task = await taskMarketplace.account.task.fetch(taskPda);
    const ataInfo = await getAccount(provider.connection, agentAta.address);

    console.log("\n  ╔══════════════════════════════════════════════╗");
    console.log("  ║         o7-ai FULL LOOP — FINAL STATE        ║");
    console.log("  ╠══════════════════════════════════════════════╣");
    console.log(
      `  ║ BRAIN Minted:  ${(supply.totalMinted.toNumber() / 1e9)
        .toString()
        .padStart(28)} ║`
    );
    console.log(
      `  ║ BRAIN Burned:  ${(supply.totalBurned.toNumber() / 1e9)
        .toString()
        .padStart(28)} ║`
    );
    console.log(
      `  ║ Agent Balance: ${(Number(ataInfo.amount) / 1e9)
        .toString()
        .padStart(28)} ║`
    );
    console.log(
      `  ║ Agent Name:    ${agent.name.padStart(28)} ║`
    );
    console.log(
      `  ║ Agent Level:   ${agent.level.toString().padStart(28)} ║`
    );
    console.log(
      `  ║ Task Status:   ${"Verified".padStart(28)} ║`
    );
    console.log(
      `  ║ Task Type:     ${"Script".padStart(28)} ║`
    );
    console.log(
      `  ║ Result URI:    ${task.resultUri.slice(0, 28).padStart(28)} ║`
    );
    console.log("  ╚══════════════════════════════════════════════╝\n");

    // All assertions pass if we got here
    assert.ok(true);
  });
});
