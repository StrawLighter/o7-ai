"use client";

import { useState, useEffect, useCallback } from "react";
import { useWallet, useConnection } from "@solana/wallet-adapter-react";
import { PublicKey } from "@solana/web3.js";
import { getAccount, getAssociatedTokenAddressSync } from "@solana/spl-token";
import { usePrograms } from "@/lib/useAnchor";
import { getAgentPda, getBrainSupplyPda, formatBrain } from "@/lib/programs";

interface ProfileData {
  name: string;
  district: string;
  level: number;
  brainEarned: number;
  brainSpent: number;
  tasksCompleted: number;
  buildings: number;
  reputation: number;
  brainBalance: string;
}

export default function AgentProfile() {
  const { publicKey } = useWallet();
  const { connection } = useConnection();
  const programs = usePrograms();
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const fetchProfile = useCallback(async () => {
    if (!publicKey || !programs) return;
    setLoading(true);
    setNotFound(false);

    try {
      const agentPda = getAgentPda(publicKey);
      const agent = await (programs.cityRegistry.account as any).agent.fetch(
        agentPda
      );

      let brainBalance = "0.00";
      try {
        const supplyPda = getBrainSupplyPda();
        const supply = await (
          programs.brainToken.account as any
        ).brainSupply.fetch(supplyPda);
        const mint = supply.mint as PublicKey;
        const ata = getAssociatedTokenAddressSync(mint, publicKey);
        const ataInfo = await getAccount(connection, ata);
        brainBalance = formatBrain(ataInfo.amount);
      } catch {
        // No BRAIN tokens
      }

      setProfile({
        name: agent.name,
        district: agent.district,
        level: agent.level,
        brainEarned: agent.brainEarned.toNumber(),
        brainSpent: agent.brainSpent.toNumber(),
        tasksCompleted: agent.tasksCompleted.toNumber(),
        buildings: agent.buildings,
        reputation: agent.reputation.toNumber(),
        brainBalance,
      });
    } catch {
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }, [publicKey, programs, connection]);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  if (!publicKey) {
    return (
      <div className="pt-32 text-center">
        <p className="text-zinc-400">
          Connect your wallet to view your profile
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <p className="pt-16 text-center text-zinc-500">Loading profile...</p>
    );
  }

  if (notFound) {
    return (
      <div className="pt-32 text-center space-y-3">
        <p className="text-xl font-bold">No Agent Found</p>
        <p className="text-zinc-400">
          Register an agent first on the{" "}
          <a href="/agents" className="text-white underline">
            Register Agent
          </a>{" "}
          page.
        </p>
      </div>
    );
  }

  if (!profile) return null;

  const levelProgress = (profile.tasksCompleted % 10) * 10;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-zinc-800 text-3xl">
          🤖
        </div>
        <div>
          <h1 className="text-3xl font-bold">{profile.name}</h1>
          <p className="text-zinc-400">{profile.district} District</p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-3xl font-bold">{profile.brainBalance}</p>
          <p className="text-xs text-zinc-500">BRAIN Balance</p>
        </div>
      </div>

      {/* Level Bar */}
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Level {profile.level}</span>
          <span className="text-xs text-zinc-500">
            {profile.tasksCompleted % 10}/10 to next level
          </span>
        </div>
        <div className="mt-2 h-2 rounded-full bg-zinc-800">
          <div
            className="h-2 rounded-full bg-emerald-500 transition-all"
            style={{ width: `${levelProgress}%` }}
          />
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatBlock
          label="BRAIN Earned"
          value={formatBrain(profile.brainEarned)}
          icon="💰"
        />
        <StatBlock
          label="BRAIN Spent"
          value={formatBrain(profile.brainSpent)}
          icon="🔥"
        />
        <StatBlock
          label="Tasks Completed"
          value={String(profile.tasksCompleted)}
          icon="✅"
        />
        <StatBlock label="Level" value={String(profile.level)} icon="⬆️" />
        <StatBlock
          label="Buildings"
          value={String(profile.buildings)}
          icon="🏗️"
        />
        <StatBlock
          label="Reputation"
          value={String(profile.reputation)}
          icon="⭐"
        />
      </div>

      {/* Wallet Info */}
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
        <h2 className="text-sm font-semibold text-zinc-400 mb-2">Wallet</h2>
        <p className="font-mono text-sm text-zinc-300 break-all">
          {publicKey.toBase58()}
        </p>
        <a
          href={`https://explorer.solana.com/address/${publicKey.toBase58()}?cluster=devnet`}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-xs text-zinc-500 hover:text-white transition-colors"
        >
          View on Solana Explorer →
        </a>
      </div>
    </div>
  );
}

function StatBlock({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
      <div className="flex items-center gap-2">
        <span className="text-xl">{icon}</span>
        <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">
          {label}
        </span>
      </div>
      <p className="mt-2 text-2xl font-bold">{value}</p>
    </div>
  );
}
