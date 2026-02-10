"use client";

import { useMemo } from "react";
import { AnchorProvider } from "@coral-xyz/anchor";
import { useConnection, useWallet } from "@solana/wallet-adapter-react";
import { AnchorWallet } from "@solana/wallet-adapter-react";
import {
  getBrainTokenProgram,
  getCityRegistryProgram,
  getTaskMarketplaceProgram,
} from "./programs";

export function useAnchorProvider(): AnchorProvider | null {
  const { connection } = useConnection();
  const wallet = useWallet();

  return useMemo(() => {
    if (!wallet.publicKey || !wallet.signTransaction || !wallet.signAllTransactions) {
      return null;
    }
    return new AnchorProvider(
      connection,
      wallet as unknown as AnchorWallet,
      { commitment: "confirmed" }
    );
  }, [connection, wallet]);
}

export function usePrograms() {
  const provider = useAnchorProvider();

  return useMemo(() => {
    if (!provider) return null;
    return {
      brainToken: getBrainTokenProgram(provider),
      cityRegistry: getCityRegistryProgram(provider),
      taskMarketplace: getTaskMarketplaceProgram(provider),
      provider,
    };
  }, [provider]);
}
