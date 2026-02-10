import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { O7Ai } from "../target/types/o7_ai";

describe("o7-ai", () => {
  // Configure the client to use the local cluster.
  anchor.setProvider(anchor.AnchorProvider.env());

  const program = anchor.workspace.o7Ai as Program<O7Ai>;

  it("Is initialized!", async () => {
    // Add your test here.
    const tx = await program.methods.initialize().rpc();
    console.log("Your transaction signature", tx);
  });
});
