// ===== 설정 =====
const API_BASE_URL = "https://receipt-ocr-1.onrender.com";
let expenseChart, statsChart;

let currentStep = 0;
const correctionSteps = ["가맹점", "총금액", "날짜", "카테고리"];
const stepFields = ["store", "amount", "date", "category"];
let ocrData = {};

// ===== 라우팅 =====
function showPage(pageId) {
    document.querySelectorAll('.page').forEach(page => page.classList.add('hidden'));
    document.getElementById(pageId).classList.remove('hidden');
    if (pageId === 'transactions') loadTransactions();
}
showPage('dashboard');

// ===== 로그인 상태 =====
function checkLoginStatus() {
    fetch(`${API_BASE_URL}/user-info`, { credentials: 'include' })
        .then(res => res.json())
        .then(data => {
            const loginBtn = document.getElementById('loginBtn');
            const logoutBtn = document.getElementById('logoutBtn');
            const userName = document.getElementById('userName');

            if (data.logged_in) {
                loginBtn.classList.add('hidden');
                logoutBtn.classList.remove('hidden');
                userName.classList.remove('hidden');
                userName.textContent = `안녕하세요, ${data.name}님`;
            } else {
                loginBtn.classList.remove('hidden');
                logoutBtn.classList.add('hidden');
                userName.classList.add('hidden');
            }
        })
        .catch(() => { /* 무시 */ });
}
checkLoginStatus();

// ===== 대시보드 =====
function updateDashboard(selectedMonth = null) {
    const url = selectedMonth
        ? `${API_BASE_URL}/api/stats?month=${selectedMonth}`
        : `${API_BASE_URL}/api/stats`;

    fetch(url, { credentials: 'include' })
        .then(res => res.json())
        .then(data => {
            document.getElementById('totalSpent').textContent = `₩${(data.total_spent || 0).toLocaleString()}`;
            document.getElementById('monthlyBudget').textContent = `₩${(data.monthly_budget || 0).toLocaleString()}`;
            document.getElementById('transactionCount').textContent = `${data.transaction_count || 0}건`;
            document.getElementById('remainingBudget').textContent = `₩${(data.remaining_budget || 0).toLocaleString()}`;

            if (document.getElementById('budgetInput')) {
                document.getElementById('budgetInput').value = data.monthly_budget || '';
            }

            // 월 선택 박스 (최초 1회 생성)
            if (!document.getElementById('monthSelector')) {
                const monthSelect = document.createElement('select');
                monthSelect.id = 'monthSelector';
                monthSelect.className = 'border rounded p-1 mb-2';
                const monthContainer = document.getElementById('monthFilter');
                const months = Object.keys(data.monthly_stats || {});
                months.reverse().forEach(month => {
                    const option = document.createElement('option');
                    option.value = month;
                    option.textContent = month;
                    if (!selectedMonth || month === selectedMonth) option.selected = true;
                    monthSelect.appendChild(option);
                });
                monthContainer.appendChild(monthSelect);

                monthSelect.addEventListener('change', () => {
                    updateDashboard(monthSelect.value);
                });
            }

            // 카테고리 도넛
            const categoryLabels = Object.keys(data.category_stats || {});
            const categoryValues = Object.values(data.category_stats || {});
            if (expenseChart) expenseChart.destroy();
            expenseChart = new Chart(document.getElementById('expenseChart'), {
                type: 'doughnut',
                data: {
                    labels: categoryLabels.length ? categoryLabels : ['데이터 없음'],
                    datasets: [{
                        data: categoryValues.length ? categoryValues : [1],
                        backgroundColor: ['#60A5FA', '#F87171', '#FBBF24', '#34D399', '#A78BFA']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
            });

            // 월별 막대
            const monthLabels = Object.keys(data.monthly_stats || {});
            const monthValues = Object.values(data.monthly_stats || {});
            if (statsChart) statsChart.destroy();
            statsChart = new Chart(document.getElementById('statsChart'), {
                type: 'bar',
                data: {
                    labels: monthLabels.length ? monthLabels : ['데이터 없음'],
                    datasets: [{ label: '월별 지출', data: monthValues.length ? monthValues : [0], backgroundColor: '#60A5FA' }]
                },
                options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
            });
        })
        .catch(() => { /* 무시 */ });
}
updateDashboard();

// ===== 예산 저장 =====
function saveBudget() {
    const val = document.getElementById('budgetInput').value.trim();
    const newBudget = parseInt(val, 10);
    if (!newBudget || newBudget <= 0) {
        alert("올바른 예산 금액을 입력하세요.");
        return;
    }

    fetch(`${API_BASE_URL}/api/budget`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ budget: newBudget })
    })
    .then(res => res.json())
    .then(resp => {
        if (resp.status === "success") {
            document.getElementById('budgetStatus').textContent = "✅ 예산이 저장되었습니다.";
            updateDashboard();
        } else {
            alert("예산 저장 실패");
        }
    })
    .catch(() => alert("네트워크 오류 발생"));
}

// ===== OCR 업로드(+ 미리보기/카테고리 유지) =====
function uploadReceipt() {
    const file = document.getElementById('receiptUpload').files[0];
    const resultDiv = document.getElementById('uploadResult');
    if (!file) return alert("파일을 선택하세요.");

    resultDiv.innerHTML = `<p class="text-blue-500">이미지 업로드 및 분석 중...</p>`;
    const formData = new FormData();
    formData.append('image', file);

    const previewURL = URL.createObjectURL(file);
    const categories = ["마트", "카페", "외식", "간식", "의류", "교통", "병원", "쇼핑", "교육", "공과금", "기타"];

    fetch(`${API_BASE_URL}/ocr`, { method: 'POST', credentials: 'include', body: formData })
        .then(res => res.json())
        .then(data => {
            ocrData = data.receipt || {};

            resultDiv.innerHTML = `
                <div class="flex gap-4 bg-white p-4 rounded border mt-2">
                    <!-- 미리보기 -->
                    <div class="w-96 flex-shrink-0">
                        <img src="${previewURL}" alt="영수증" class="border rounded w-full object-contain">
                    </div>

                    <!-- OCR 결과/수정 -->
                    <div class="flex-1">
                        <h3 class="font-bold mb-2 text-green-600">✅ OCR 인식 완료</h3>
                        <p><b>가맹점:</b> <input id="edit-store" class="border p-1 rounded w-full" value="${ocrData.가맹점 || ''}"></p>
                        <p><b>총금액:</b> <input id="edit-amount" class="border p-1 rounded w-full" value="${ocrData.총금액 || ''}"></p>
                        <p><b>날짜:</b> <input id="edit-date" class="border p-1 rounded w-full" value="${ocrData.날짜 || ''}"></p>
                        <p><b>카테고리:</b>
                            <select id="edit-category" class="border p-1 rounded w-full mb-2">
                                ${categories.map(cat => `<option value="${cat}" ${ocrData.카테고리 === cat ? 'selected' : ''}>${cat}</option>`).join('')}
                            </select>
                            <input id="edit-category-custom" class="hidden border p-1 rounded w-full text-sm mt-1" placeholder="직접 입력하세요">
                            <button id="toggle-category-input" class="text-blue-500 text-xs mt-1">직접 입력</button>
                        </p>

                        <button id="save-direct" class="mt-4 bg-blue-500 text-white px-3 py-1 rounded">변경 저장</button>
                        <button id="toggleRawText" class="mt-4 bg-gray-300 px-3 py-1 rounded text-sm">원본 보기</button>
                        <pre id="rawTextBlock" class="mt-2 p-2 bg-gray-100 rounded text-xs hidden">${data.raw_text || '원본 데이터 없음'}</pre>
                    </div>
                </div>
            `;

            document.getElementById('toggleRawText').addEventListener('click', () => {
                document.getElementById('rawTextBlock').classList.toggle('hidden');
            });

            document.getElementById('toggle-category-input').addEventListener('click', () => {
                const select = document.getElementById('edit-category');
                const input = document.getElementById('edit-category-custom');
                const button = document.getElementById('toggle-category-input');

                input.classList.toggle('hidden');
                if (!input.classList.contains('hidden')) {
                    input.value = select.value;
                    button.textContent = '드롭다운 사용';
                } else {
                    select.value = input.value || select.value;
                    button.textContent = '직접 입력';
                }
            });

            document.getElementById('save-direct').addEventListener('click', () => {
                const updatedStore = document.getElementById('edit-store').value.trim();
                const updatedAmount = document.getElementById('edit-amount').value.trim();
                const updatedDate = document.getElementById('edit-date').value.trim();
                const updatedCategory = document.getElementById('edit-category-custom').classList.contains('hidden')
                    ? document.getElementById('edit-category').value
                    : document.getElementById('edit-category-custom').value;

                fetch(`${API_BASE_URL}/api/user-data`, { credentials: 'include' })
                    .then(res => res.json())
                    .then(rows => {
                        if (!rows.length) return alert("거래 내역 없음");
                        const latestId = rows[0].id;
                        const ocrOriginal = rows[0].ocr_store;

                        patchUpdate(latestId, "store", updatedStore, ocrOriginal);
                        patchUpdate(latestId, "amount", updatedAmount, null);
                        patchUpdate(latestId, "date", updatedDate, null);
                        patchUpdate(latestId, "category", updatedCategory, null);

                        alert("✅ 변경사항이 저장되었습니다.");
                        updateDashboard();
                        loadTransactions();
                    });
            });

            // 단계별 교정 시작 (원본 동작 유지)
            startCorrection();
        })
        .catch(err => {
            console.error(err);
            alert("업로드 중 오류가 발생했습니다.");
        });
}

// ===== 단계별 교정 UI =====
function startCorrection() {
    currentStep = 0;
    const box = document.getElementById('correctionBox');
    if (box) {
        box.classList.remove('hidden');
        showStep();
    }
}

function showStep() {
    const label = correctionSteps[currentStep];
    document.getElementById('correction-step-label').textContent = `${label} 수정`;
    // 한글 키와 매핑
    const map = { "가맹점": "가맹점", "총금액": "총금액", "날짜": "날짜", "카테고리": "카테고리" };
    const val = ocrData[map[label]] || "";
    document.getElementById('correction-input').value = val;
}

document.getElementById('save-correction-btn').onclick = () => {
    const inputValue = document.getElementById('correction-input').value.trim();
    if (!inputValue) return alert("값을 입력하세요.");
    const field = stepFields[currentStep];

    fetch(`${API_BASE_URL}/api/user-data`, { credentials: 'include' })
        .then(res => res.json())
        .then(data => {
            if (!data.length) return alert("거래 내역이 없습니다.");
            const latestId = data[0].id;
            const ocrOriginal = data[0].ocr_store;

            return fetch(`${API_BASE_URL}/api/correct-transaction/${latestId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                credentials: 'include',
                body: JSON.stringify({
                    field: field,
                    value: inputValue,
                    ocr_original: field === "store" ? (ocrOriginal || inputValue) : null
                })
            });
        })
        .then(res => res.json())
        .then(resp => {
            if (resp.status === "success") {
                document.getElementById('correction-status').textContent = `${correctionSteps[currentStep]} 저장 완료`;
                currentStep++;
                if (currentStep < correctionSteps.length) {
                    setTimeout(showStep, 600);
                } else {
                    document.getElementById('correction-status').textContent = "✅ 모든 교정 완료!";
                    setTimeout(() => {
                        document.getElementById('correctionBox').classList.add('hidden');
                        updateDashboard();
                        loadTransactions();
                    }, 1200);
                }
            } else {
                alert("교정 저장 실패");
            }
        })
        .catch(() => alert("네트워크 오류"));
};

// ===== 거래 내역 (인라인 수정 + 삭제 추가) =====
function loadTransactions() {
    fetch(`${API_BASE_URL}/api/user-data`, { credentials: 'include' })
        .then(res => res.json())
        .then(data => {
            const tableBody = document.querySelector("#transactions tbody");
            if (!tableBody) return;

            if (data.length === 0) {
                tableBody.innerHTML = `<tr><td colspan="6" class="text-center">거래 내역이 없습니다.</td></tr>`;
                return;
            }
            tableBody.innerHTML = "";
            data.forEach(item => {
                tableBody.innerHTML += `
                    <tr data-id="${item.id}" data-ocr="${item.ocr_store}">
                        <td class="border p-2"><input class="editable border p-1 w-full" data-field="date" value="${item.date || ''}"></td>
                        <td class="border p-2"><input class="editable border p-1 w-full" data-field="store" value="${item.store || ''}"></td>
                        <td class="border p-2"><input class="editable border p-1 w-full" data-field="amount" type="number" value="${item.amount || 0}"></td>
                        <td class="border p-2"><input class="editable border p-1 w-full" data-field="category" value="${item.category || ''}"></td>
                        <td class="border p-2">
                            <button class="save-btn bg-blue-500 text-white px-2 py-1 rounded text-sm">저장</button>
                        </td>
                        <td class="border p-2 text-center">
                            <button class="delete-btn bg-red-500 text-white px-2 py-1 rounded text-sm">삭제</button>
                        </td>
                    </tr>`;
            });
            attachSaveHandlers();
            attachDeleteHandlers();
        })
        .catch(() => { /* 무시 */ });
}

function attachSaveHandlers() {
    document.querySelectorAll(".save-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const row = btn.closest("tr");
            const id = row.dataset.id;
            const ocrOriginal = row.dataset.ocr;
            row.querySelectorAll(".editable").forEach(input => {
                const field = input.dataset.field;
                const value = input.value.trim();
                if (value !== undefined && value !== null) {
                    patchUpdate(id, field, value, ocrOriginal);
                }
            });
        });
    });
}

// ===== 삭제 핸들러 =====
function attachDeleteHandlers() {
    document.querySelectorAll(".delete-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const row = btn.closest("tr");
            const id = row.dataset.id;
            if (!id) return;

            if (!confirm("정말 삭제하시겠습니까?")) return;

            deleteTransaction(id)
                .then(ok => {
                    if (ok) {
                        // 행 삭제 + 대시보드 갱신
                        row.remove();
                        updateDashboard();
                        // 테이블이 비면 안내 행 추가
                        const tbody = document.querySelector("#transactions tbody");
                        if (tbody && !tbody.querySelector("tr")) {
                            tbody.innerHTML = `<tr><td colspan="6" class="text-center">거래 내역이 없습니다.</td></tr>`;
                        }
                    } else {
                        alert("삭제 실패");
                    }
                })
                .catch(() => alert("네트워크 오류"));
        });
    });
}

// ===== 삭제 API (DELETE 우선, POST 폴백) =====
async function deleteTransaction(id) {
    try {
        // 1) RESTful DELETE 우선
        const del = await fetch(`${API_BASE_URL}/api/transactions/${id}`, {
            method: "DELETE",
            credentials: "include"
        });
        if (del.ok) return true;

        // 2) 폴백: POST /api/delete { id }
        const fb = await fetch(`${API_BASE_URL}/api/delete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ id })
        });
        if (!fb.ok) return false;
        const resp = await fb.json();
        return resp && (resp.status === "success" || resp.deleted === true);
    } catch (e) {
        console.error("삭제 오류:", e);
        return false;
    }
}

// ===== PATCH 업데이트 (원본 유지) =====
function patchUpdate(id, field, value, ocrOriginal) {
    fetch(`${API_BASE_URL}/api/correct-transaction/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: 'include',
        body: JSON.stringify({
            field: field,
            value: value,
            ocr_original: field === "store" ? (ocrOriginal || value) : null
        })
    })
    .then(res => res.json())
    .then(resp => {
        if (resp.status === "success") {
            console.log(`${field} 업데이트 성공`);
        } else {
            alert("업데이트 실패: " + (resp.error || ""));
        }
    })
    .catch(err => {
        console.error("업데이트 에러:", err);
        alert("네트워크 오류");
    });
}
