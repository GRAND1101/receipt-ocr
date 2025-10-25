const API_BASE_URL = "https://receipt-ocr-1.onrender.com";
let expenseChart, statsChart;
let txItems = [];
let lastDeleted = null; // { id, index, data }
let undoTimer = null;

let currentStep = 0;
const correctionSteps = ["가맹점", "총금액", "날짜", "카테고리"];
const stepFields = ["store", "amount", "date", "category"];
let ocrData = {};

/* =========================
   페이지 전환 및 로그인 상태
========================= */
function showPage(pageId) {
  document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
  document.getElementById(pageId).classList.remove("hidden");
  if (pageId === "transactions") loadTransactions();
}
showPage("dashboard");

function checkLoginStatus() {
  fetch(`${API_BASE_URL}/user-info`, { credentials: "include" })
    .then((res) => res.json())
    .then((data) => {
      const loginBtn = document.getElementById("loginBtn");
      const logoutBtn = document.getElementById("logoutBtn");
      const userName = document.getElementById("userName");

      if (data.logged_in) {
        loginBtn.classList.add("hidden");
        logoutBtn.classList.remove("hidden");
        userName.classList.remove("hidden");
        userName.textContent = `안녕하세요, ${data.name}님`;
      } else {
        loginBtn.classList.remove("hidden");
        logoutBtn.classList.add("hidden");
        userName.classList.add("hidden");
      }
    });
}
checkLoginStatus();

/* =========================
   대시보드 / 통계
========================= */
function updateDashboard(selectedMonth = null) {
  const url = selectedMonth
    ? `${API_BASE_URL}/api/stats?month=${selectedMonth}`
    : `${API_BASE_URL}/api/stats`;

  fetch(url, { credentials: "include" })
    .then((res) => res.json())
    .then((data) => {
      document.getElementById("totalSpent").textContent = `₩${(
        data.total_spent || 0
      ).toLocaleString()}`;
      document.getElementById("monthlyBudget").textContent = `₩${(
        data.monthly_budget || 0
      ).toLocaleString()}`;
      document.getElementById("transactionCount").textContent = `${
        data.transaction_count || 0
      }건`;
      document.getElementById("remainingBudget").textContent = `₩${(
        data.remaining_budget || 0
      ).toLocaleString()}`;

      if (document.getElementById("budgetInput")) {
        document.getElementById("budgetInput").value =
          data.monthly_budget || "";
      }

      // ✅ 월 선택 박스 생성 (한 번만)
      if (!document.getElementById("monthSelector")) {
        const monthSelect = document.createElement("select");
        monthSelect.id = "monthSelector";
        monthSelect.className = "border rounded p-1 mb-2";
        const monthContainer = document.getElementById("monthFilter");
        const months = Object.keys(data.monthly_stats || {});
        months.reverse().forEach((month) => {
          const option = document.createElement("option");
          option.value = month;
          option.textContent = month;
          monthSelect.appendChild(option);
        });
        monthContainer.appendChild(monthSelect);
        monthSelect.addEventListener("change", () =>
          updateDashboard(monthSelect.value)
        );
      }

      // ✅ 카테고리별 원형 그래프
      const categoryLabels = Object.keys(data.category_stats || {});
      const categoryValues = Object.values(data.category_stats || {});
      if (expenseChart) expenseChart.destroy();
      expenseChart = new Chart(document.getElementById("expenseChart"), {
        type: "doughnut",
        data: {
          labels: categoryLabels.length ? categoryLabels : ["데이터 없음"],
          datasets: [
            {
              data: categoryValues.length ? categoryValues : [1],
              backgroundColor: [
                "#60A5FA",
                "#F87171",
                "#FBBF24",
                "#34D399",
                "#A78BFA",
              ],
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: "bottom" } },
        },
      });

      // ✅ 월별 막대 그래프
      const monthLabels = Object.keys(data.monthly_stats || {});
      const monthValues = Object.values(data.monthly_stats || {});
      if (statsChart) statsChart.destroy();
      statsChart = new Chart(document.getElementById("statsChart"), {
        type: "bar",
        data: {
          labels: monthLabels.length ? monthLabels : ["데이터 없음"],
          datasets: [
            {
              label: "월별 지출",
              data: monthValues.length ? monthValues : [0],
              backgroundColor: "#60A5FA",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: { y: { beginAtZero: true } },
        },
      });
    });
}
updateDashboard();

/* =========================
   예산 저장
========================= */
function saveBudget() {
  const newBudget = parseInt(
    document.getElementById("budgetInput").value.trim()
  );
  if (!newBudget || newBudget <= 0) return alert("올바른 금액을 입력하세요.");

  fetch(`${API_BASE_URL}/api/budget`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ budget: newBudget }),
  })
    .then((r) => r.json())
    .then((resp) => {
      if (resp.status === "success") {
        document.getElementById("budgetStatus").textContent =
          "✅ 예산이 저장되었습니다.";
        updateDashboard();
      }
    });
}

/* =========================
   OCR 업로드
========================= */
function uploadReceipt() {
  const file = document.getElementById("receiptUpload").files[0];
  if (!file) return alert("파일을 선택하세요.");
  const resultDiv = document.getElementById("uploadResult");
  resultDiv.innerHTML = `<p class="text-blue-500">이미지 업로드 중...</p>`;
  const fd = new FormData();
  fd.append("image", file);

  fetch(`${API_BASE_URL}/ocr`, { method: "POST", credentials: "include", body: fd })
    .then((r) => r.json())
    .then((data) => {
      resultDiv.innerHTML = `<p class="text-green-600">✅ OCR 완료: ${data.receipt?.가맹점 ?? "-"} / ₩${(
        data.receipt?.총금액 || 0
      ).toLocaleString()}</p>`;
      updateDashboard();
      loadTransactions();
    })
    .catch(() => {
      resultDiv.innerHTML = `<p class="text-red-500">오류 발생</p>`;
    });
}

/* =========================
   거래 내역 (삭제 + 되돌리기)
========================= */
function loadTransactions() {
  fetch(`${API_BASE_URL}/api/user-data`, { credentials: "include" })
    .then((r) => r.json())
    .then((data) => {
      txItems = data;
      const tbody = document.querySelector("#transactions tbody");
      if (!txItems.length) {
        tbody.innerHTML =
          '<tr><td colspan="5" class="text-center p-4 text-gray-500">거래 내역이 없습니다.</td></tr>';
        return;
      }

      tbody.innerHTML = txItems
        .map(
          (t, i) => `
        <tr>
          <td class="border p-2">${t.date || ""}</td>
          <td class="border p-2">${t.store || ""}</td>
          <td class="border p-2">${(t.amount || 0).toLocaleString()}</td>
          <td class="border p-2">${t.category || ""}</td>
          <td class="border p-2 text-center">
            <button class="bg-red-500 text-white px-2 py-1 rounded text-sm" onclick="deleteTransaction(${t.id}, ${i})">삭제</button>
          </td>
        </tr>`
        )
        .join("");
    });
}

function deleteTransaction(id, index) {
  if (!confirm("이 항목을 삭제하시겠습니까?")) return;
  const removed = txItems.splice(index, 1)[0];
  lastDeleted = { id, index, data: removed };
  renderAfterDelete();
  showUndoToast();

  fetch(`${API_BASE_URL}/api/transactions/${id}`, {
    method: "DELETE",
    credentials: "include",
  }).catch(() => {
    alert("삭제 실패");
    loadTransactions();
  });
}

function renderAfterDelete() {
  const tbody = document.querySelector("#transactions tbody");
  if (!txItems.length) {
    tbody.innerHTML =
      '<tr><td colspan="5" class="text-center text-gray-500 p-4">거래 내역이 없습니다.</td></tr>';
  } else {
    tbody.innerHTML = txItems
      .map(
        (t, i) => `
      <tr>
        <td class="border p-2">${t.date}</td>
        <td class="border p-2">${t.store}</td>
        <td class="border p-2">${t.amount.toLocaleString()}</td>
        <td class="border p-2">${t.category}</td>
        <td class="border p-2 text-center">
          <button class="bg-red-500 text-white px-2 py-1 rounded text-sm" onclick="deleteTransaction(${t.id}, ${i})">삭제</button>
        </td>
      </tr>`
      )
      .join("");
  }
}

/* 되돌리기 토스트 */
function showUndoToast() {
  const toast = document.getElementById("undo-toast");
  const text = toast.querySelector(".toast-text");
  const undoBtn = toast.querySelector(".btn-undo");
  toast.classList.remove("hidden");
  let remain = 5;
  text.textContent = `삭제되었습니다. 되돌리시겠어요? (${remain}초)`;

  clearInterval(undoTimer);
  undoTimer = setInterval(() => {
    remain--;
    if (remain <= 0) {
      clearInterval(undoTimer);
      toast.classList.add("hidden");
      lastDeleted = null;
    } else {
      text.textContent = `삭제되었습니다. 되돌리시겠어요? (${remain}초)`;
    }
  }, 1000);

  undoBtn.onclick = () => {
    clearInterval(undoTimer);
    toast.classList.add("hidden");
    if (!lastDeleted) return;
    txItems.splice(lastDeleted.index, 0, lastDeleted.data);
    renderAfterDelete();
    fetch(`${API_BASE_URL}/api/transactions/${lastDeleted.id}/restore`, {
      method: "POST",
      credentials: "include",
    })
      .then(() => {
        lastDeleted = null;
        updateDashboard();
      })
      .catch(() => alert("복원 실패"));
  };
}
