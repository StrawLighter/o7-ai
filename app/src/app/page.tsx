"use client";

import { useEffect, useState, useCallback } from "react";
import { useWallet, useConnection } from "@solana/wallet-adapter-react";
import { PublicKey } from "@solana/web3.js";
import { getAccount, getAssociatedTokenAddressSync } from "@solana/spl-token";
import { usePrograms } from "@/lib/useAnchor";
import {
  getBrainSupplyPda,
  getAgentPda,
  formatBrain,
} from "@/lib/programs";

interface DashboardData {
  brainBalance: string;
  totalMinted: string;
  totalBurned: string;
  agentRegistered: boolean;
  agentName: string;
  tasksCompleted: number;
  level: number;
}

export default function Dashboard() {
  const { publicKey } = useWallet();
  const { connection } = useConnection();
  const programs = usePrograms();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    if (!publicKey || !programs) return;
    setLoading(true);

    try {
      const result: DashboardData = {
        brainBalance: "0.00",
        totalMinted: "0.00",
        totalBurned: "0.00",
        agentRegistered: false,
        agentName: "",
        tasksCompleted: 0,
        level: 0,
      };

      // Fetch brain supply
      try {
        const supplyPda = getBrainSupplyPda();
        const supply = await (programs.brainToken.account as any).brainSupply.fetch(supplyPda);
        result.totalMinted = formatBrain(supply.totalMinted);
        result.totalBurned = formatBrain(supply.totalBurned);

        // Fetch BRAIN balance for connected wallet
        const mint = supply.mint as PublicKey;
        try {
          const ata = getAssociatedTokenAddressSync(mint, publicKey);
          const ataInfo = await getAccount(connection, ata);
          result.brainBalance = formatBrain(ataInfo.amount);
        } catch {
          // No ATA yet
        }
      } catch {
        // No brain supply initialized yet
      }

      // Fetch agent
      try {
        const agentPda = getAgentPda(publicKey);
        const agent = await (programs.cityRegistry.account as any).agent.fetch(agentPda);
        result.agentRegistered = true;
        result.agentName = agent.name;
        result.tasksCompleted = agent.tasksCompleted.toNumber();
        result.level = agent.level;
      } catch {
        // No agent registered
      }

      setData(result);
    } catch (e) {
      console.error("Dashboard fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, [publicKey, programs, connection]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (!publicKey) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 pt-32">
        <h1 className="text-4xl font-bold">o7-ai</h1>
        <p className="text-zinc-400">Connect your wallet to enter the city</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Dashboard</h1>
        <p className="mt-1 text-zinc-400">
          Connected: {publicKey.toBase58().slice(0, 4)}...
          {publicKey.toBase58().slice(-4)}
        </p>
      </div>

      {loading ? (
        <p className="text-zinc-500">Loading on-chain data...</p>
      ) : data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="BRAIN Balance"
            value={data.brainBalance}
            sub="tokens"
          />
          <StatCard
            label="Total Minted"
            value={data.totalMinted}
            sub="supply"
          />
          <StatCard
            label="Total Burned"
            value={data.totalBurned}
            sub="deflation"
          />
          <StatCard
            label="Agent Status"
            value={data.agentRegistered ? data.agentName : "Not Registered"}
            sub={
              data.agentRegistered
                ? `Level ${data.level} · ${data.tasksCompleted} tasks`
                : "Register on the Agents page"
            }
          />
        </div>
      ) : (
        <p className="text-zinc-500">
          No on-chain data found. Register an agent and complete tasks to see
          your stats.
        </p>
      )}

      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-6">
        <h2 className="text-lg font-semibold">Devnet Programs</h2>
        <div className="mt-3 space-y-2 font-mono text-xs text-zinc-400">
          <Row label="brain_token" addr="27q16KwXGDooHCCUKvJGrfNXubJh1zFnwXS7XsCXNpVf" />
          <Row label="city_registry" addr="Cb4F2nafRNbtWKPuWwfjMofq5hZQ6PKttpWLCokCGNtL" />
          <Row label="task_marketplace" addr="5nnAtvyXk388f3SwQXihxiGxfyPQzy9U3dzPohvkH9fY" />
          <Row label="staking_vault" addr="CdTaBicv2ppsi8y9YxACvb73qsT2r3A12c26tDTH2unS" />
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
      <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
        {label}
      </p>
      <p className="mt-2 text-2xl font-bold">{value}</p>
      <p className="mt-1 text-xs text-zinc-500">{sub}</p>
    </div>
  );
}

function Row({ label, addr }: { label: string; addr: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-zinc-500">{label}</span>
      <a
        href={`https://explorer.solana.com/address/${addr}?cluster=devnet`}
        target="_blank"
        rel="noopener noreferrer"
        className="hover:text-white transition-colors"
      >
        {addr.slice(0, 8)}...{addr.slice(-4)}
      </a>
    </div>
  );
}
