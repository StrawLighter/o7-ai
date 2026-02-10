import { AnchorProvider, Program, BN } from "@coral-xyz/anchor";
import { Connection, PublicKey, clusterApiUrl } from "@solana/web3.js";

import brainTokenIdl from "./brain_token.json";
import cityRegistryIdl from "./city_registry.json";
import taskMarketplaceIdl from "./task_marketplace.json";

// ── Program IDs (devnet deployed) ───────────────────────────────────────────
export const BRAIN_TOKEN_ID = new PublicKey(
  "27q16KwXGDooHCCUKvJGrfNXubJh1zFnwXS7XsCXNpVf"
);
export const CITY_REGISTRY_ID = new PublicKey(
  "Cb4F2nafRNbtWKPuWwfjMofq5hZQ6PKttpWLCokCGNtL"
);
export const TASK_MARKETPLACE_ID = new PublicKey(
  "5nnAtvyXk388f3SwQXihxiGxfyPQzy9U3dzPohvkH9fY"
);
export const STAKING_VAULT_ID = new PublicKey(
  "CdTaBicv2ppsi8y9YxACvb73qsT2r3A12c26tDTH2unS"
);

export const DEVNET_RPC = clusterApiUrl("devnet");

// ── PDA Derivations ─────────────────────────────────────────────────────────
export function getBrainSupplyPda(): PublicKey {
  const [pda] = PublicKey.findProgramAddressSync(
    [Buffer.from("brain-supply")],
    BRAIN_TOKEN_ID
  );
  return pda;
}

export function getAgentPda(owner: PublicKey): PublicKey {
  const [pda] = PublicKey.findProgramAddressSync(
    [Buffer.from("agent"), owner.toBuffer()],
    CITY_REGISTRY_ID
  );
  return pda;
}

export function getTaskPda(taskId: BN): PublicKey {
  const [pda] = PublicKey.findProgramAddressSync(
    [Buffer.from("task"), taskId.toArrayLike(Buffer, "le", 8)],
    TASK_MARKETPLACE_ID
  );
  return pda;
}

// ── Program Constructors ────────────────────────────────────────────────────
export function getBrainTokenProgram(provider: AnchorProvider) {
  return new Program(brainTokenIdl as any, provider);
}

export function getCityRegistryProgram(provider: AnchorProvider) {
  return new Program(cityRegistryIdl as any, provider);
}

export function getTaskMarketplaceProgram(provider: AnchorProvider) {
  return new Program(taskMarketplaceIdl as any, provider);
}

// ── Helpers ─────────────────────────────────────────────────────────────────
export function formatBrain(amount: BN | number | bigint): string {
  const n = typeof amount === "number" ? amount : Number(amount);
  return (n / 1e9).toFixed(2);
}

export function taskStatusLabel(
  status: Record<string, unknown>
): string {
  if ("open" in status || "Open" in status) return "Open";
  if ("inProgress" in status || "InProgress" in status) return "In Progress";
  if ("completed" in status || "Completed" in status) return "Completed";
  if ("verified" in status || "Verified" in status) return "Verified";
  return "Unknown";
}

export function taskTypeLabel(
  taskType: Record<string, unknown>
): string {
  if ("script" in taskType || "Script" in taskType) return "Script";
  if ("voiceover" in taskType || "Voiceover" in taskType) return "Voiceover";
  if ("copy" in taskType || "Copy" in taskType) return "Copy";
  if ("ugc" in taskType || "Ugc" in taskType) return "UGC";
  return "Unknown";
}
