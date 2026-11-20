// Global State
let currentJobId = "test_demo_sample";
let currentCandidates = [];
let selectedCandidateIndex = 0;
let selectedLayout = "blur";
let allCheats = [];
let activeCheatCategory = "All";

// DOM Ready initialization
document.addEventListener("DOMContentLoaded", () => {
  // Check if test demo job exists and load candidates
  fetchJobDetails("test_demo_sample");
  loadTrends();
  loadStreams();
  loadPayouts();
  loadCheats();
});

// Tab Switching (Updated for GTA VI Pill Nav)
function switchTab(tabId) {
  const tabs = ["studio", "trends", "streams", "clips", "payouts", "cheats"];
  tabs.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    const btn = document.getElementById(`tab-btn-${t}`);
    if (el) {
      if (t === tabId) {
        el.classList.remove("hidden");
      } else {
        el.classList.add("hidden");
      }
    }
    if (btn) {
      if (t === tabId) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    }
  });

  if (tabId === "clips") {
    loadRenderedClips();
  } else if (tabId === "payouts") {
    loadPayouts();
  }
}

// ----------------- CLIP STUDIO LOGIC -----------------

function loadSampleDemo() {
  document.getElementById("video-url-input").value = "https://www.youtube.com/watch?v=QdBZY2fkU-0";
  fetchJobDetails("test_demo_sample");
}

function fetchJobDetails(jobId) {
  fetch(`/api/jobs/${jobId}`)
    .then(r => r.json())
    .then(data => {
      if (data && data.candidates && data.candidates.length > 0) {
        currentJobId = jobId;
        currentCandidates = data.candidates;
        renderCandidates(data.candidates);

        // If clips already exist, load the first one into player
        if (data.clips && data.clips.length > 0) {
          loadVideoIntoPlayer(data.clips[0].url);
        }
      }
    })
    .catch(err => console.log("Job details notice:", err));
}

function handleFindMoments(e) {
  e.preventDefault();
  const url = document.getElementById("video-url-input").value.trim();
  const maxMinutes = parseInt(document.getElementById("max-minutes-select").value) || 15;
  const topCount = parseInt(document.getElementById("top-count-select").value) || 5;

  if (!url) return;

  const btn = document.getElementById("btn-find-moments");
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i><span>Analyzing Audio...</span>`;

  showTerminal("Analyzing Audio & Multi-Signal Viral Engagement...", 0);

  fetch("/api/moments/find", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, max_minutes: maxMinutes, top_count: topCount })
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        throw new Error(data.error);
      }
      pollTask(data.task_id, (result) => {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-magnifying-glass-chart"></i><span>Find Moments</span>`;
        if (result && result.candidates) {
          currentJobId = result.job_id;
          currentCandidates = result.candidates;
          renderCandidates(result.candidates);
        }
      });
    })
    .catch(err => {
      alert("Error: " + err.message);
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-magnifying-glass-chart"></i><span>Find Moments</span>`;
    });
}

function renderCandidates(candidates) {
  const container = document.getElementById("candidates-list");
  const countBadge = document.getElementById("candidates-count-badge");
  countBadge.textContent = `${candidates.length} Moments`;

  if (!candidates || candidates.length === 0) {
    container.innerHTML = `
      <div class="p-8 text-center border border-dashed border-purple-500/30 rounded-2xl text-purple-300/50">
        <p class="font-outfit">No candidate moments detected.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  candidates.forEach((c, idx) => {
    const isSelected = idx === selectedCandidateIndex;
    const card = document.createElement("div");
    card.className = `moment-card p-4 cursor-pointer ${
      isSelected ? "selected" : ""
    }`;
    card.onclick = () => selectCandidate(idx);

    card.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center space-x-3.5">
          <div class="w-9 h-9 rounded-full bg-gradient-to-r from-pink-500 to-purple-600 flex items-center justify-center font-outfit font-black text-white text-xs shadow-[0_0_12px_rgba(255,0,122,0.5)]">
            #${c.pick || idx + 1}
          </div>
          <div>
            <h4 class="font-outfit font-bold text-sm text-white flex items-center space-x-2">
              <span>${c.label || "Viral Highlight"}</span>
              <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-pink-500/15 text-pink-300 border border-pink-500/30 font-semibold">
                ${c.start_str} - ${c.end_str} (${c.duration}s)
              </span>
            </h4>
            <p class="text-xs text-purple-200/70 mt-0.5 font-normal">${c.reason || "Loudness spike + speech enthusiasm"}</p>
          </div>
        </div>
        <div class="text-right">
          <span class="text-xs font-outfit font-black text-pink-400 glow-text-pink">${c.score}/100</span>
          <span class="block text-[9px] uppercase tracking-wider text-purple-300/60 font-outfit">Viral Score</span>
        </div>
      </div>

      <!-- Transcript preview snippet -->
      ${
        c.transcript_snippet
          ? `<div class="mt-2.5 text-xs italic text-purple-200/80 bg-[#070112]/70 p-2.5 rounded-xl border border-purple-500/20 font-sans">
              "${c.transcript_snippet}"
            </div>`
          : ""
      }
    `;
    container.appendChild(card);
  });

  // Pre-fill hook with candidate #1
  if (candidates[0]) {
    setHookText(candidates[0].label || "WAIT FOR IT 💀");
  }
}

function selectCandidate(idx) {
  selectedCandidateIndex = idx;
  const cards = document.querySelectorAll(".moment-card");
  cards.forEach((card, i) => {
    if (i === idx) {
      card.classList.add("selected");
    } else {
      card.classList.remove("selected");
    }
  });

  const c = currentCandidates[idx];
  if (c && c.label) {
    setHookText(c.label);
  }
}

function selectLayout(layout) {
  selectedLayout = layout;
  const layouts = ["blur", "facecam", "fill", "react"];
  layouts.forEach(l => {
    const btn = document.getElementById(`layout-btn-${l}`);
    if (btn) {
      if (l === layout) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    }
  });
}

function setHookText(text) {
  const input = document.getElementById("hook-text-input");
  if (input) {
    input.value = text;
  }
}

function handleCutSelectedClip() {
  if (!currentCandidates || currentCandidates.length === 0) {
    alert("Please scan or load candidate moments first!");
    return;
  }

  const cand = currentCandidates[selectedCandidateIndex] || currentCandidates[0];
  const hook = document.getElementById("hook-text-input").value.trim() || cand.label;
  const color = document.querySelector('input[name="subtitle-color"]:checked')?.value || "cyan";

  const btn = document.getElementById("btn-render-clip");
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i><span>Rendering 1080x1920 Short...</span>`;

  showTerminal(`Compositing Short (Layout: ${selectedLayout}, Color: ${color})...`, 0);

  fetch("/api/clip/cut", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_id: currentJobId,
      pick: cand.pick || selectedCandidateIndex + 1,
      start: cand.start,
      end: cand.end,
      layout: selectedLayout,
      hook: hook,
      color: color
    })
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) throw new Error(data.error);
      pollTask(data.task_id, (result) => {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-play"></i><span>Render 1080x1920 Short (-14 LUFS)</span>`;
        if (result && result.url) {
          loadVideoIntoPlayer(result.url);
        }
      });
    })
    .catch(err => {
      alert("Error: " + err.message);
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-play"></i><span>Render 1080x1920 Short (-14 LUFS)</span>`;
    });
}

function loadVideoIntoPlayer(videoUrl) {
  const player = document.getElementById("short-video-player");
  const dlBtn = document.getElementById("btn-download-clip");
  if (player) {
    player.src = videoUrl;
    player.load();
    player.play().catch(() => {});
  }
  if (dlBtn) {
    dlBtn.href = videoUrl;
    dlBtn.classList.remove("opacity-50", "pointer-events-none");
  }
}

function copyClipUrl() {
  const player = document.getElementById("short-video-player");
  if (player && player.src) {
    navigator.clipboard.writeText(player.src);
    alert("Copied short video URL to clipboard!");
  }
}

// ----------------- TERMINAL & TASK POLLING -----------------

function showTerminal(name, progress = 0) {
  const cont = document.getElementById("terminal-container");
  const nameLabel = document.getElementById("task-name-label");
  const progLabel = document.getElementById("task-progress-label");
  const out = document.getElementById("terminal-output");

  cont.classList.remove("hidden");
  nameLabel.textContent = name;
  progLabel.textContent = `${progress}%`;
  out.innerHTML = `<div>[READY] Initializing Vice City GPU/CPU Engine...</div>`;
}

function pollTask(taskId, onComplete) {
  const interval = setInterval(() => {
    fetch(`/api/tasks/${taskId}`)
      .then(r => r.json())
      .then(task => {
        const progLabel = document.getElementById("task-progress-label");
        const out = document.getElementById("terminal-output");
        if (progLabel) progLabel.textContent = `${task.progress}%`;

        if (out && task.logs) {
          out.innerHTML = task.logs.map(line => `<div>${escapeHtml(line)}</div>`).join("");
          out.scrollTop = out.scrollHeight;
        }

        if (task.status === "completed") {
          clearInterval(interval);
          if (onComplete) onComplete(task.result);
        } else if (task.status === "failed") {
          clearInterval(interval);
          alert("Task Failed: " + (task.error || "Unknown error"));
        }
      })
      .catch(err => {
        console.error("Polling error:", err);
      });
  }, 750);
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ----------------- TAB 2: TRENDS RADAR -----------------

function loadTrends() {
  const grid = document.getElementById("trends-grid");
  fetch("/api/trends")
    .then(r => r.json())
    .then(trends => {
      if (!trends || trends.length === 0) {
        grid.innerHTML = `<p class="col-span-full text-center text-purple-300/50">No trending videos found.</p>`;
        return;
      }
      grid.innerHTML = "";
      trends.forEach((t, i) => {
        const card = document.createElement("div");
        card.className = "gta-glass-card p-3.5 hover:border-pink-500/50 flex flex-col justify-between";
        card.innerHTML = `
          <div>
            <div class="relative rounded-xl overflow-hidden aspect-video mb-3 bg-black/60 border border-purple-500/20">
              <img src="${t.thumbnail}" alt="" class="w-full h-full object-cover">
              <span class="absolute bottom-1.5 right-1.5 px-2 py-0.5 rounded-md text-[10px] bg-black/80 font-mono text-white">
                ${t.duration_str}
              </span>
              ${
                t.has_heatmap
                  ? `<span class="absolute top-1.5 left-1.5 px-2.5 py-0.5 rounded-full text-[10px] bg-gradient-to-r from-pink-500 to-purple-600 font-outfit font-bold text-white shadow-[0_0_8px_rgba(255,0,122,0.6)]">
                      🔥 Heatmap
                    </span>`
                  : ""
              }
            </div>
            <h4 class="font-outfit font-bold text-xs text-white line-clamp-2">${t.title}</h4>
            <p class="text-[11px] text-purple-300/70 mt-1">${t.channel}</p>
          </div>
          <div class="mt-3.5 pt-3 border-t border-purple-500/20 flex items-center justify-between">
            <div>
              <span class="text-xs font-outfit font-black text-cyan-400 glow-text-cyan">${t.velocity.toLocaleString()}</span>
              <span class="text-[9px] text-purple-300/50 block uppercase font-outfit">views / hr</span>
            </div>
            <button onclick="clipFromUrl('${t.url}')" class="gta-btn-secondary px-3 py-1.5 text-xs font-outfit font-bold text-pink-300 hover:text-white transition">
              Open in Studio
            </button>
          </div>
        `;
        grid.appendChild(card);
      });
    });
}

function refreshTrends() {
  const query = document.getElementById("trends-query-input").value.trim();
  const grid = document.getElementById("trends-grid");
  grid.innerHTML = `<div class="col-span-full text-center py-10"><i class="fa-solid fa-spinner fa-spin text-2xl text-pink-500"></i><p class="mt-2 text-xs text-purple-300 font-outfit">Refreshing trends radar...</p></div>`;

  fetch("/api/trends/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: query, limit: 15 })
  })
    .then(r => r.json())
    .then(data => {
      pollTask(data.task_id, () => loadTrends());
    });
}

function clipFromUrl(url) {
  document.getElementById("video-url-input").value = url;
  switchTab("studio");
}

// ----------------- TAB 3: LIVE STREAMS -----------------

function loadStreams() {
  const grid = document.getElementById("streams-grid");
  fetch("/api/streams")
    .then(r => r.json())
    .then(streams => {
      if (!streams || streams.length === 0) {
        grid.innerHTML = `<p class="col-span-full text-center text-purple-300/50">No active streams found.</p>`;
        return;
      }
      grid.innerHTML = "";
      streams.forEach(s => {
        const isTwitch = s.platform === "Twitch";
        const card = document.createElement("div");
        card.className = "gta-glass-card p-3.5 hover:border-rose-500/50 flex flex-col justify-between";
        card.innerHTML = `
          <div>
            <div class="relative rounded-xl overflow-hidden aspect-video mb-3 bg-black/60 border border-purple-500/20">
              <img src="${s.thumbnail}" alt="" class="w-full h-full object-cover">
              <span class="absolute top-1.5 left-1.5 px-2.5 py-0.5 rounded-full text-[10px] bg-red-600 font-outfit font-bold text-white flex items-center space-x-1 shadow-[0_0_8px_rgba(239,68,68,0.7)]">
                <span class="w-1.5 h-1.5 rounded-full bg-white animate-pulse"></span>
                <span>LIVE</span>
              </span>
              <span class="absolute top-1.5 right-1.5 px-2.5 py-0.5 rounded-full text-[10px] ${
                isTwitch ? "bg-purple-600" : "bg-red-700"
              } font-outfit font-bold text-white">
                ${s.platform}
              </span>
            </div>
            <h4 class="font-outfit font-bold text-xs text-white line-clamp-2">${s.title}</h4>
            <p class="text-[11px] text-purple-300/70 mt-1">${s.channel}</p>
          </div>
          <div class="mt-3.5 pt-3 border-t border-purple-500/20 flex items-center justify-between">
            <div>
              <span class="text-xs font-outfit font-black text-rose-400">${(s.viewers || 0).toLocaleString()}</span>
              <span class="text-[9px] text-purple-300/50 block uppercase font-outfit">viewers</span>
            </div>
            <button onclick="clipFromUrl('${s.url}')" class="gta-btn-secondary px-3 py-1.5 text-xs font-outfit font-bold text-rose-300 hover:text-white transition">
              Clip Stream
            </button>
          </div>
        `;
        grid.appendChild(card);
      });
    });
}

function refreshStreams() {
  const grid = document.getElementById("streams-grid");
  grid.innerHTML = `<div class="col-span-full text-center py-10"><i class="fa-solid fa-spinner fa-spin text-2xl text-rose-500"></i><p class="mt-2 text-xs text-purple-300 font-outfit">Refreshing active streams...</p></div>`;

  fetch("/api/streams/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "GTA", limit: 15 })
  })
    .then(r => r.json())
    .then(data => {
      pollTask(data.task_id, () => loadStreams());
    });
}

// ----------------- TAB 4: MY CLIPS -----------------

function loadRenderedClips() {
  const grid = document.getElementById("my-clips-grid");
  fetch("/api/jobs")
    .then(r => r.json())
    .then(jobs => {
      let allClips = [];
      jobs.forEach(j => {
        if (j.clips) {
          j.clips.forEach(c => allClips.push(c));
        }
      });

      if (allClips.length === 0) {
        grid.innerHTML = `<p class="col-span-full text-center text-purple-300/50 py-12 font-outfit">No short clips rendered yet. Go to Clip Studio to render your first 9:16 short!</p>`;
        return;
      }

      grid.innerHTML = "";
      allClips.forEach(c => {
        const card = document.createElement("div");
        card.className = "gta-glass-card p-3 flex flex-col justify-between";
        card.innerHTML = `
          <div>
            <div class="relative rounded-xl overflow-hidden aspect-[9/16] bg-black/80 mb-2.5 border border-purple-500/20 shadow-lg">
              <video src="${c.url}" class="w-full h-full object-cover" muted></video>
              <span class="absolute bottom-1.5 right-1.5 px-2 py-0.5 rounded-md text-[9px] bg-black/80 font-mono text-purple-200">
                ${c.duration ? c.duration.toFixed(0) + "s" : "9:16"}
              </span>
            </div>
            <h5 class="text-xs font-outfit font-bold text-white truncate">${c.filename}</h5>
            <p class="text-[10px] text-purple-300/60 mt-0.5 font-mono">${c.size_mb ? c.size_mb + " MB" : ""}</p>
          </div>
          <div class="mt-2.5 pt-2 border-t border-purple-500/20 flex items-center justify-between gap-1.5">
            <button onclick="loadVideoIntoPlayer('${c.url}'); switchTab('studio');" class="flex-1 gta-btn-secondary py-1 text-[10px] font-outfit font-bold text-center">
              Play
            </button>
            <a href="${c.url}" download class="px-2.5 py-1 gta-btn-secondary text-[10px] font-bold">
              <i class="fa-solid fa-download"></i>
            </a>
          </div>
        `;
        grid.appendChild(card);
      });
    });
}

// ----------------- TAB 5: PAYOUTS & ROI -----------------

function loadPayouts() {
  fetch("/api/payouts")
    .then(r => r.json())
    .then(data => {
      document.getElementById("stat-total-views").textContent = (data.total_views || 0).toLocaleString();
      document.getElementById("stat-total-revenue").textContent = `$${(data.total_revenue || 0).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      })}`;
      document.getElementById("stat-avg-cpm").textContent = `$${(data.average_cpm || 2.5).toFixed(2)}`;
      document.getElementById("stat-total-posts").textContent = (data.total_campaigns || 0);

      const tbody = document.getElementById("payouts-table-body");
      tbody.innerHTML = "";
      (data.campaigns || []).forEach(c => {
        const tr = document.createElement("tr");
        tr.className = "hover:bg-purple-900/20 transition";
        tr.innerHTML = `
          <td class="py-3 font-outfit font-semibold text-white">${c.title}</td>
          <td class="py-3 text-purple-300/70">${c.platform}</td>
          <td class="py-3 font-mono text-purple-200">${(c.views || 0).toLocaleString()}</td>
          <td class="py-3 text-purple-300/70">$${(c.cpm || 2.5).toFixed(2)}</td>
          <td class="py-3 font-outfit font-bold text-emerald-400 glow-text-cyan">$${(c.revenue || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
          <td class="py-3 text-purple-300/50">${c.date || "N/A"}</td>
        `;
        tbody.appendChild(tr);
      });
    });
}

function handleAddPost(e) {
  e.preventDefault();
  const title = document.getElementById("post-title").value.trim();
  const platform = document.getElementById("post-platform").value;
  const views = parseInt(document.getElementById("post-views").value) || 0;
  const cpm = parseFloat(document.getElementById("post-cpm").value) || 2.5;
  const url = document.getElementById("post-url").value.trim();

  fetch("/api/payouts/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, platform, views, cpm, url })
  })
    .then(r => r.json())
    .then(() => {
      document.getElementById("post-title").value = "";
      document.getElementById("post-url").value = "";
      loadPayouts();
    });
}

// ----------------- TAB 6: CHEATS & SECRETS -----------------

function loadCheats() {
  fetch("/api/cheats")
    .then(r => r.json())
    .then(cheats => {
      allCheats = cheats;
      renderCheats();
    });
}

function setCheatCategory(cat) {
  activeCheatCategory = cat;
  const btns = document.querySelectorAll(".cheat-cat-btn");
  btns.forEach(b => {
    if (b.textContent.trim() === cat) {
      b.classList.add("active", "border-pink-500/40", "text-white", "font-bold");
      b.classList.remove("border-purple-500/30", "text-purple-300");
    } else {
      b.classList.remove("active", "border-pink-500/40", "text-white", "font-bold");
      b.classList.add("border-purple-500/30", "text-purple-300");
    }
  });
  renderCheats();
}

function filterCheats() {
  renderCheats();
}

function renderCheats() {
  const grid = document.getElementById("cheats-grid");
  const query = (document.getElementById("cheats-search-input")?.value || "").toLowerCase().trim();

  const filtered = allCheats.filter(c => {
    const matchesCat = activeCheatCategory === "All" || c.category === activeCheatCategory;
    const matchesQuery =
      !query ||
      c.name.toLowerCase().includes(query) ||
      c.description.toLowerCase().includes(query) ||
      (c.pc && c.pc.toLowerCase().includes(query));
    return matchesCat && matchesQuery;
  });

  if (filtered.length === 0) {
    grid.innerHTML = `<p class="col-span-full text-center text-purple-300/50 py-10 font-outfit">No cheats found matching criteria.</p>`;
    return;
  }

  grid.innerHTML = "";
  filtered.forEach(c => {
    const card = document.createElement("div");
    card.className = "gta-glass-card p-4 hover:border-amber-400/50 transition flex flex-col justify-between";
    card.innerHTML = `
      <div>
        <div class="flex items-center justify-between mb-2">
          <h4 class="font-outfit font-bold text-sm text-white">${c.name}</h4>
          <span class="text-[10px] px-2.5 py-0.5 rounded-full bg-amber-400/15 text-amber-300 font-outfit font-bold border border-amber-400/30">
            ${c.category}
          </span>
        </div>
        <p class="text-xs text-purple-200/70 mb-3">${c.description}</p>
      </div>

      <div class="space-y-1.5 pt-2.5 border-t border-purple-500/20 font-mono text-[11px]">
        ${
          c.pc
            ? `<div class="flex items-center justify-between bg-[#080214] px-2.5 py-1.5 rounded-lg border border-purple-500/15">
                <span class="text-purple-400 font-sans">PC:</span>
                <span class="text-amber-300 font-bold">${c.pc}</span>
                <button onclick="copyToClipboard('${c.pc}')" class="text-purple-300 hover:text-white"><i class="fa-regular fa-copy"></i></button>
              </div>`
            : ""
        }
        ${
          c.ps
            ? `<div class="bg-[#080214] px-2.5 py-1.5 rounded-lg text-[10px] text-purple-200 border border-purple-500/15">
                <span class="text-purple-400 font-sans">PlayStation:</span> ${c.ps}
              </div>`
            : ""
        }
        ${
          c.xbox
            ? `<div class="bg-[#080214] px-2.5 py-1.5 rounded-lg text-[10px] text-purple-200 border border-purple-500/15">
                <span class="text-purple-400 font-sans">Xbox:</span> ${c.xbox}
              </div>`
            : ""
        }
      </div>
    `;
    grid.appendChild(card);
  });
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text);
  alert(`Copied "${text}" to clipboard!`);
}
