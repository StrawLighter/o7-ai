"use client";

import { useState, useEffect, useCallback } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { PublicKey, SystemProgram } from "@solana/web3.js";
import { BN } from "@coral-xyz/anchor";
import { usePrograms } from "@/lib/useAnchor";
import {
  getTaskPda,
  formatBrain,
  taskStatusLabel,
  taskTypeLabel,
} from "@/lib/programs";

interface TaskData {
  publicKey: PublicKey;
  id: number;
  creator: PublicKey;
  taskType: Record<string, unknown>;
  description: string;
  rewardBrain: BN;
  assignedAgent: PublicKey;
  status: Record<string, unknown>;
  resultUri: string;
}

const TASK_TYPES = [
  { label: "Script", value: { script: {} } },
  { label: "Voiceover", value: { voiceover: {} } },
  { label: "Copy", value: { copy: {} } },
  { label: "UGC", value: { ugc: {} } },
];

const STATUS_COLORS: Record<string, string> = {
  Open: "bg-emerald-500/20 text-emerald-400",
  "In Progress": "bg-yellow-500/20 text-yellow-400",
  Completed: "bg-blue-500/20 text-blue-400",
  Verified: "bg-purple-500/20 text-purple-400",
};

export default function TaskBoard() {
  const { publicKey } = useWallet();
  const programs = usePrograms();
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Create task form
  const [showCreate, setShowCreate] = useState(false);
  const [newDesc, setNewDesc] = useState("");
  const [newType, setNewType] = useState(TASK_TYPES[0]);
  const [newReward, setNewReward] = useState("100");
  const [newTaskId, setNewTaskId] = useState("");

  const fetchTasks = useCallback(async () => {
    if (!programs) return;
    setLoading(true);
    try {
      const allTasks = await (programs.taskMarketplace.account as any).task.all();
      const parsed: TaskData[] = allTasks.map((t: any) => ({
        publicKey: t.publicKey,
        id: t.account.id.toNumber(),
        creator: t.account.creator,
        taskType: t.account.taskType,
        description: t.account.description,
        rewardBrain: t.account.rewardBrain,
        assignedAgent: t.account.assignedAgent,
        status: t.account.status,
        resultUri: t.account.resultUri,
      }));
      parsed.sort((a, b) => b.id - a.id);
      setTasks(parsed);
    } catch (e) {
      console.error("Fetch tasks error:", e);
    } finally {
      setLoading(false);
    }
  }, [programs]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  async function handleCreateTask() {
    if (!publicKey || !programs || !newTaskId) return;
    setActionLoading("create");
    try {
      const taskId = new BN(newTaskId);
      const taskPda = getTaskPda(taskId);
      const rewardLamports = new BN(
        Math.floor(parseFloat(newReward) * 1e9)
      );

      await programs.taskMarketplace.methods
        .createTask(taskId, newType.value, newDesc, rewardLamports)
        .accounts({
          creator: publicKey,
          task: taskPda,
          systemProgram: SystemProgram.programId,
        })
        .rpc();

      setShowCreate(false);
      setNewDesc("");
      setNewTaskId("");
      await fetchTasks();
    } catch (e: any) {
      console.error("Create task error:", e);
      alert("Failed: " + (e.message?.slice(0, 100) || "unknown error"));
    } finally {
      setActionLoading(null);
    }
  }

  async function handleAssign(task: TaskData) {
    if (!publicKey || !programs) return;
    setActionLoading(`assign-${task.id}`);
    try {
      await programs.taskMarketplace.methods
        .assignTask(publicKey)
        .accounts({
          creator: publicKey,
          task: task.publicKey,
        })
        .rpc();
      await fetchTasks();
    } catch (e: any) {
      console.error("Assign error:", e);
      alert("Failed: " + (e.message?.slice(0, 100) || "unknown error"));
    } finally {
      setActionLoading(null);
    }
  }

  async function handleSubmit(task: TaskData) {
    if (!publicKey || !programs) return;
    const uri = prompt("Enter result URI (e.g. arweave/ipfs link):");
    if (!uri) return;
    setActionLoading(`submit-${task.id}`);
    try {
      await programs.taskMarketplace.methods
        .submitResult(uri)
        .accounts({
          agent: publicKey,
          task: task.publicKey,
        })
        .rpc();
      await fetchTasks();
    } catch (e: any) {
      console.error("Submit error:", e);
      alert("Failed: " + (e.message?.slice(0, 100) || "unknown error"));
    } finally {
      setActionLoading(null);
    }
  }

  async function handleVerify(task: TaskData) {
    if (!publicKey || !programs) return;
    setActionLoading(`verify-${task.id}`);
    try {
      await programs.taskMarketplace.methods
        .verifyTask()
        .accounts({
          creator: publicKey,
          task: task.publicKey,
        })
        .rpc();
      await fetchTasks();
    } catch (e: any) {
      console.error("Verify error:", e);
      alert("Failed: " + (e.message?.slice(0, 100) || "unknown error"));
    } finally {
      setActionLoading(null);
    }
  }

  if (!publicKey) {
    return (
      <div className="pt-32 text-center">
        <p className="text-zinc-400">Connect your wallet to view tasks</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Task Board</h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-black hover:bg-zinc-200"
        >
          {showCreate ? "Cancel" : "+ New Task"}
        </button>
      </div>

      {/* Create Task Form */}
      {showCreate && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 space-y-4">
          <h2 className="font-semibold">Create New Task</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs text-zinc-400 mb-1">
                Task ID (unique number)
              </label>
              <input
                type="number"
                value={newTaskId}
                onChange={(e) => setNewTaskId(e.target.value)}
                placeholder="e.g. 42"
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-400 mb-1">
                Reward (BRAIN)
              </label>
              <input
                type="number"
                value={newReward}
                onChange={(e) => setNewReward(e.target.value)}
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Type</label>
            <div className="flex gap-2">
              {TASK_TYPES.map((t) => (
                <button
                  key={t.label}
                  onClick={() => setNewType(t)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    newType.label === t.label
                      ? "bg-white text-black"
                      : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">
              Description
            </label>
            <textarea
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              maxLength={256}
              rows={2}
              placeholder="Describe the task..."
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
            />
          </div>
          <button
            onClick={handleCreateTask}
            disabled={actionLoading === "create" || !newTaskId || !newDesc}
            className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-black hover:bg-zinc-200 disabled:opacity-50"
          >
            {actionLoading === "create" ? "Creating..." : "Create Task"}
          </button>
        </div>
      )}

      {/* Task List */}
      {loading ? (
        <p className="text-zinc-500">Loading tasks from devnet...</p>
      ) : tasks.length === 0 ? (
        <p className="text-zinc-500">
          No tasks found. Create one to get started!
        </p>
      ) : (
        <div className="space-y-3">
          {tasks.map((task) => {
            const statusStr = taskStatusLabel(task.status);
            const isCreator = publicKey.equals(task.creator);
            const isAssigned = publicKey.equals(task.assignedAgent);

            return (
              <div
                key={task.id}
                className="rounded-lg border border-zinc-800 bg-zinc-950 p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs text-zinc-500">#{task.id}</span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          STATUS_COLORS[statusStr] ||
                          "bg-zinc-800 text-zinc-400"
                        }`}
                      >
                        {statusStr}
                      </span>
                      <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
                        {taskTypeLabel(task.taskType)}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-zinc-200">
                      {task.description}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
                      <span>
                        Reward: {formatBrain(task.rewardBrain)} BRAIN
                      </span>
                      <span>
                        Creator: {task.creator.toBase58().slice(0, 6)}...
                      </span>
                      {!task.assignedAgent.equals(PublicKey.default) && (
                        <span>
                          Agent:{" "}
                          {task.assignedAgent.toBase58().slice(0, 6)}...
                        </span>
                      )}
                      {task.resultUri && (
                        <span className="truncate max-w-48">
                          Result: {task.resultUri}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex shrink-0 gap-2">
                    {statusStr === "Open" && isCreator && (
                      <button
                        onClick={() => handleAssign(task)}
                        disabled={actionLoading === `assign-${task.id}`}
                        className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                      >
                        {actionLoading === `assign-${task.id}`
                          ? "..."
                          : "Assign Self"}
                      </button>
                    )}
                    {statusStr === "In Progress" && isAssigned && (
                      <button
                        onClick={() => handleSubmit(task)}
                        disabled={actionLoading === `submit-${task.id}`}
                        className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
                      >
                        {actionLoading === `submit-${task.id}`
                          ? "..."
                          : "Submit Result"}
                      </button>
                    )}
                    {statusStr === "Completed" && isCreator && (
                      <button
                        onClick={() => handleVerify(task)}
                        disabled={actionLoading === `verify-${task.id}`}
                        className="rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-500 disabled:opacity-50"
                      >
                        {actionLoading === `verify-${task.id}`
                          ? "..."
                          : "Verify"}
                      </button>
                    )}
                  </div>
                </div>

                {/* Status Flow */}
                <div className="mt-3 flex items-center gap-1 text-[10px]">
                  {["Open", "In Progress", "Completed", "Verified"].map(
                    (step, i) => {
                      const active =
                        [
                          "Open",
                          "In Progress",
                          "Completed",
                          "Verified",
                        ].indexOf(statusStr) >= i;
                      return (
                        <div key={step} className="flex items-center gap-1">
                          {i > 0 && (
                            <div
                              className={`h-px w-4 ${
                                active ? "bg-emerald-500" : "bg-zinc-700"
                              }`}
                            />
                          )}
                          <span
                            className={`rounded-full px-1.5 py-0.5 ${
                              active
                                ? "bg-emerald-500/20 text-emerald-400"
                                : "bg-zinc-800 text-zinc-600"
                            }`}
                          >
                            {step}
                          </span>
                        </div>
                      );
                    }
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
