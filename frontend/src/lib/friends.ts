export type FriendshipStatus = "none" | "friends" | "request_sent" | "request_received";

export const FRIEND_LABELS: Record<FriendshipStatus, string> = {
  none: "Add friend",
  request_sent: "Request sent",
  request_received: "Accept request",
  friends: "Friends",
};

const CLASS_BASE = "friend-btn cursor-pointer shrink-0 px-3 py-1.5 rounded-full text-xs font-bold border transition-all";
const CLASS_BY_STATUS: Record<FriendshipStatus, string> = {
  none: "bg-emerald-600/80 hover:bg-emerald-500 text-white border-emerald-500/40",
  request_sent: "bg-zinc-800 hover:bg-red-900/40 text-zinc-300 hover:text-red-300 border-zinc-700 hover:border-red-500/40",
  request_received: "bg-blue-600/80 hover:bg-blue-500 text-white border-blue-500/40",
  friends: "bg-zinc-800 hover:bg-red-900/40 text-zinc-300 hover:text-red-300 border-zinc-700 hover:border-red-500/40",
};

export const friendButtonClass = (status: FriendshipStatus) => `${CLASS_BASE} ${CLASS_BY_STATUS[status]}`;

function render(btn: HTMLButtonElement, status: FriendshipStatus) {
  btn.dataset.status = status;
  btn.className = friendButtonClass(status);
  btn.textContent = FRIEND_LABELS[status];
  btn.title = status === "friends" ? "Click to remove friend" : status === "request_sent" ? "Click to cancel request" : "";
}

// Wires up every `.friend-btn[data-user-id][data-status]` on the page.
export function initFriendButtons(token: string) {
  document.querySelectorAll<HTMLButtonElement>(".friend-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const userId = Number(btn.dataset.userId);
      const status = (btn.dataset.status ?? "none") as FriendshipStatus;
      if (status === "friends" && !confirm("Remove this friend?")) return;

      const call =
        status === "none" ? ["POST", `/api/proxy/friends/${userId}/request`]
        : status === "request_received" ? ["POST", `/api/proxy/friends/${userId}/accept`]
        : ["DELETE", `/api/proxy/friends/${userId}`];

      btn.disabled = true;
      try {
        const res = await fetch(call[1], { method: call[0], headers: { Authorization: `Bearer ${token}` } });
        if (!res.ok) throw new Error("Request failed");
        const data = await res.json();
        render(btn, (data.status ?? "none") as FriendshipStatus);
      } catch {
        // leave the button unchanged on failure
      } finally {
        btn.disabled = false;
      }
    });
  });
}
