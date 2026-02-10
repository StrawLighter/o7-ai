"use client";

import { useState, useEffect, useCallback } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { SystemProgram } from "@solana/web3.js";
import { usePrograms } from "@/lib/useAnchor";
import { getAgentPda } from "@/lib/programs";

const DISTRICTS = ["Studio", "Agency", "Downtown", "Lab", "Marketplace"];

export default function AgentRegistration() {
  const { publicKey } = useWallet();
  const programs = usePrograms();
  const [name, setName] = useState("");
  const [district, setDistrict] = useState(DISTRICTS[0]);
  const [status, setStatus] = useState<
    "idle" | "loading" | "success" | "error" | "exists"
  >("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [existingAgent, setExistingAgent] = useState<any>(null);

  const checkExisting = useCallback(async () => {
    if (!publicKey || !programs) return;
    try {
      const agentPda = getAgentPda(publicKey);
      const agent = await (programs.cityRegistry.account as any).agent.fetch(agentPda);
      setExistingAgent(agent);
      setStatus("exists");
    } catch {
      // No agent yet
    }
  }, [publicKey, programs]);

  useEffect(() => {
    checkExisting();
  }, [checkExisting]);

  async function handleRegister() {
    if (!publicKey || !programs) return;
    if (name.length === 0 || name.length > 32) {
      setErrorMsg("Name must be 1-32 characters");
      setStatus("error");
      return;
    }

    setStatus("loading");
    setErrorMsg("");

    try {
      const agentPda = getAgentPda(publicKey);

      const tx = await programs.cityRegistry.methods
        .registerAgent(name, district)
        .accounts({
          owner: publicKey,
          agent: agentPda,
          systemProgram: SystemProgram.programId,
        })
        .rpc();

      console.log("registerAgent tx:", tx);
      setStatus("success");

      const agent = await (programs.cityRegistry.account as any).agent.fetch(agentPda);
      setExistingAgent(agent);
    } catch (e: any) {
      console.error("Register error:", e);
      setErrorMsg(e.message?.slice(0, 120) || "Transaction failed");
      setStatus("error");
    }
  }

  if (!publicKey) {
    return (
      <div className="pt-32 text-center">
        <p className="text-zinc-400">Connect your wallet to register an agent</p>
      </div>
    );
  }

  if (status === "exists" || status === "success") {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Agent Registered</h1>
        {existingAgent && (
          <div className="max-w-md rounded-lg border border-zinc-800 bg-zinc-950 p-6 space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/20 text-2xl">
                🤖
              </div>
              <div>
                <p className="text-lg font-bold">{existingAgent.name}</p>
                <p className="text-sm text-zinc-400">
                  {existingAgent.district}
                </p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 pt-2">
              <MiniStat label="Level" value={existingAgent.level} />
              <MiniStat label="Tasks" value={existingAgent.tasksCompleted?.toNumber?.()} />
              <MiniStat label="BRAIN Earned" value={(existingAgent.brainEarned?.toNumber?.() / 1e9 || 0).toFixed(2)} />
              <MiniStat label="Buildings" value={existingAgent.buildings} />
            </div>
            {status === "success" && (
              <p className="text-sm text-emerald-400">
                Agent registered on devnet!
              </p>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Register Agent</h1>
      <p className="text-zinc-400">
        Create your AI agent to start completing tasks and earning BRAIN.
      </p>

      <div className="max-w-md space-y-4">
        <div>
          <label className="block text-sm font-medium text-zinc-300 mb-1.5">
            Agent Name
          </label>
          <input
            type="text"
            maxLength={32}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. AgentSmith"
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
          />
          <p className="mt-1 text-xs text-zinc-500">{name.length}/32</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-zinc-300 mb-1.5">
            District
          </label>
          <div className="flex flex-wrap gap-2">
            {DISTRICTS.map((d) => (
              <button
                key={d}
                onClick={() => setDistrict(d)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  district === d
                    ? "bg-white text-black"
                    : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                }`}
              >
                {d}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={handleRegister}
          disabled={status === "loading" || !name}
          className="mt-2 w-full rounded-md bg-white px-4 py-2.5 font-semibold text-black transition-colors hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {status === "loading" ? "Registering..." : "Register Agent"}
        </button>

        {status === "error" && (
          <p className="text-sm text-red-400">{errorMsg}</p>
        )}
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded-md bg-zinc-900 px-3 py-2">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-lg font-bold">{String(value ?? 0)}</p>
    </div>
  );
}
