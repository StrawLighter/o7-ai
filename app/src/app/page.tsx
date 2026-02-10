"use client";

import { useWallet } from "@solana/wallet-adapter-react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";

export default function Home() {
  const { publicKey } = useWallet();

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-black text-white">
      <main className="flex flex-col items-center gap-8">
        <h1 className="text-5xl font-bold tracking-tight">o7-ai</h1>
        <p className="text-lg text-zinc-400">AI agent city on Solana</p>
        <WalletMultiButton />
        {publicKey && (
          <p className="text-sm text-zinc-500">
            Connected: {publicKey.toBase58().slice(0, 8)}...
          </p>
        )}
      </main>
    </div>
  );
}
