# Phương pháp luận — BuBu-Trading

Tài liệu này ghi lại toàn bộ giả định, công thức và quy trình kiểm định đứng sau
website. Mục tiêu là để người đọc tái lập được kết quả và tự đánh giá độ tin cậy,
thay vì chỉ nhìn vào một con số tổng hợp.

---

## 1. Nguồn dữ liệu

| Hạng mục | Chi tiết |
|---|---|
| Thư viện | `vnstock` 3.2.5 |
| Nhà cung cấp | VCI (Vietcap) — endpoint `trading.vietcap.com.vn` |
| Universe | VN100 (HOSE), lấy từ `…/api/price/symbols/getByGroup?group=VN100` |
| Chỉ số tham chiếu | `VNINDEX`, dùng cho bộ lọc xu hướng |
| Khoảng thời gian | 2016-01-04 → ngày chạy pipeline (khoảng 2.690 phiên) |
| Cache | `data/raw/{SYMBOL}_{YYYY}.csv.gz` |

### 1.1 Xử lý TLS trong mạng nội bộ

Proxy của mạng doanh nghiệp chèn chứng thư gốc vào chuỗi TLS (Kaspersky Endpoint
Security, BSC Root CA). Bundle `certifi` mặc định của Python không chứa các chứng
thư này nên mọi request HTTPS báo `CERTIFICATE_VERIFY_FAILED`. Thay vì tắt xác
thực chứng thư, `bubu.utils.inject_truststore()` nạp `truststore` để dùng trực
tiếp Windows Root store.

### 1.2 Điều tiết nhịp gọi API

`vnai` (thư viện phụ trợ của vnstock) áp trần **60 request/phút** cho nguồn VCI
và gọi thẳng `sys.exit()` khi vượt trần — nghĩa là không thể bắt bằng `try/except`
thông thường và toàn bộ tiến trình bị hủy giữa chừng. `bubu.data.RateLimiter` giữ
nhịp ở **48 request/phút**; khi vẫn chạm trần, `DataFetchInterrupted` được phát ra để
pipeline dừng mềm và lần chạy sau tiếp tục từ cache.

### 1.3 Chuẩn hoá giá

Một số nguồn trả giá theo nghìn VND. `_normalize()` kiểm tra trung vị giá: nếu
dưới 1.000 thì nhân 1.000 để đưa về VND. Dữ liệu VCI đã điều chỉnh cổ tức và chia
tách.

---

## 2. Đặc thù thị trường Việt Nam và cách mô hình hoá

### 2.1 Biên độ ±7% và bước giá HOSE

Giá trần và giá sàn được tính từ giá tham chiếu (giá đóng cửa phiên trước), làm
tròn theo bước giá HOSE:

| Khung giá (VND) | Bước giá |
|---|---|
| < 10.000 | 10 |
| 10.000 – 49.950 | 50 |
| ≥ 50.000 | 100 |

```
giá_trần = floor(giá_tham_chiếu × 1,07 / bước_giá) × bước_giá
giá_sàn  = ceil (giá_tham_chiếu × 0,93 / bước_giá) × bước_giá
```

Luật giao dịch tương ứng:

- **Không vào lệnh khi đóng cửa tại giá trần.** Lệnh mua tại giá trần khó khớp và dễ
  bị đảo chiều cuối phiên. Nếu breakout rơi đúng phiên trần, tín hiệu bị bỏ; hệ thống
  đánh giá lại ở phiên kế tiếp.
- **Treo lệnh thoát khi kẹt giá sàn.** Khi cổ phiếu đóng cửa tại giá sàn, lệnh bán
  không khớp được. Engine đặt cờ `force_exit` và thực thi tại giá mở cửa của phiên
  kế tiếp khi giá đã thoát khỏi sàn.

### 2.2 Chu kỳ thanh toán T+2.5

Cổ phiếu mua tại phiên `t` chỉ được bán từ phiên `t+2`. Engine mô hình hoá bằng
`MarketConfig.settlement_lag = 2`:

- Mỗi Unit mới vào bị khoá đúng 2 phiên trước khi stop loss có hiệu lực.
- Khi tín hiệu thoát xuất hiện, chỉ phần cổ phiếu **đã về tài khoản** được bán;
  phần còn lại treo sang phiên sau.
- Điều kiện gia tăng Unit cũng yêu cầu Unit trước đó đã về tài khoản, nên tại mọi
  thời điểm có tối đa một Unit chưa bán được.

Đây là điểm khác biệt lớn so với backtest bỏ qua T+: nếu không mô hình hoá, stop
loss có thể "cứu" vị thế trong hai phiên đầu — điều bất khả thi trên thực tế.

### 2.3 Cấm bán khống cổ phiếu cơ sở

Toàn bộ engine là **long-only**. Không có nhánh lệnh bán nào được mở khi chưa có vị
thế. Hệ quả: Turtle System 1 đầy đủ (vốn có cả nhánh short) không thể áp dụng trên
cổ phiếu cơ sở; muốn giao dịch hai chiều phải dùng hợp đồng tương lai VN30F1M, nằm
ngoài phạm vi nghiên cứu này.

### 2.4 Thanh khoản phân tán

Hai lớp kiểm soát:

1. **Bộ lọc ADV**: giá trị giao dịch bình quân 20 phiên (dịch 1 phiên để chống
   look-ahead) phải đạt tối thiểu 30 tỷ VND/phiên.
2. **Trần tỷ trọng**: tối đa 20% NAV cho một Unit và 60% NAV cho một mã.

Bộ lọc ADV là **điểm yếu nghiêm trọng nhất của đặc tả gốc** và cần đọc kỹ. Bảng
dưới là tỷ lệ symbol-day đạt ngưỡng theo năm:

| Năm | ADV ≥ 30 tỷ | ADV ≥ 10 tỷ |
|---|---|---|
| 2016 | 2,6% | — |
| 2017 | 8,4% | — |
| 2018 | 18,8% | — |
| 2019 | 8,3% | — |
| 2020 | 21,3% | — |
| 2021 | 58,2% | — |
| 2022 | 62,2% | — |
| 2023 | 59,6% | — |
| 2024 | 74,7% | — |
| 2025 | 78,8% | — |

*(Số liệu đầy đủ cho cả ba ngưỡng 10/30/50 tỷ nằm trong `site/data/liquidity.json`,
hiển thị trên tab "Đặc thù Việt Nam".)*

Hệ quả trực tiếp: trong giai đoạn 2016–2020, ngưỡng 30 tỷ khoá gần như toàn bộ tín
hiệu. Tần suất giao dịch thực tế theo từng mã vì thế chỉ khoảng **1 lệnh/năm**, chứ
không phải 6–7 lệnh/năm như đặc tả giả định. Khi hạ ngưỡng xuống 10 tỷ hoặc bỏ hẳn,
Calmar trung vị tăng từ 0,00 lên 0,04 và 0,08 — xem bảng ablation trên website.

**Lưu ý về slippage.** Mô hình dùng slippage cố định 0,10% cho mọi mã, không phụ
thuộc ADV. Điều này khiến các mã thanh khoản thấp trông hấp dẫn hơn thực tế, và là
lý do chính khiến kịch bản "bỏ lọc ADV" cho kết quả tốt hơn. Kết luận đúng phải là:
*ngưỡng 30 tỷ là quá cao so với giai đoạn 2016–2020*, chứ không phải *thanh khoản
không quan trọng*.

---

## 3. Cấu trúc chiến lược

### 3.1 Quy tắc

```
N_t     = ATR_Wilder(high, low, close, atr_period)[t]
upper_t = max(high[t-entry_window : t])      # loại trừ phiên t
lower_t = min(low [t-exit_window  : t])

VÀO LỆNH  nếu:  close[t] > upper_t
                và ADV20[t] ≥ adv_min
                và (không lọc thị trường hoặc VNINDEX[t] > SMA200(VNINDEX)[t])
                và close[t] < giá_trần[t]
                và số phiên niêm yết ≥ entry_window + 1

GIA TĂNG UNIT nếu: đang có vị thế, số Unit < max_units,
                   Unit trước đã về tài khoản (≥ 2 phiên),
                   close[t] ≥ giá_vào_Unit_cuối + pyramid_atr × N

STOP LOSS nếu:  low[t] ≤ giá_vào_Unit_mới_nhất − stop_atr × N
                (chỉ áp dụng cho Unit đã về tài khoản)

THOÁT nếu:  close[t] < lower_t
```

Mọi chỉ báo Donchian đều tính trên dữ liệu **trước** ngày tín hiệu. ADV cũng dịch
1 phiên. ATR dùng giá trị tại `t` vì tại thời điểm đóng cửa, biên độ trong phiên đã
được biết.

### 3.2 Position sizing

```
Unit = (risk_per_unit × Equity) / (stop_atr × N)     # chế độ "risk" (mặc định)
Unit = (risk_per_unit × Equity) / N                  # chế độ "volatility" — Turtle gốc
```

**Mâu thuẫn trong đặc tả gốc.** Đặc tả nêu đồng thời ba điều không tương thích:
(1) `Unit = 1% × Equity / (ATR × Giá)`; (2) "mỗi Unit chiếm khoảng 5–7% NAV";
(3) "tổng exposure không quá 60% NAV" với tối đa 4 Unit/mã.

Với N ≈ 3% giá:

- Công thức Turtle gốc (`1% × Equity / N`) cho mỗi Unit ≈ **33% NAV** → 4 Unit = 133% NAV.
- Công thức (1) trong đặc tả còn lớn hơn về mặt khối lượng, tương đương 33% NAV/Unit.
- Để một Unit chỉ chiếm 5–7% NAV thì `risk_per_unit` phải vào khoảng 0,18% — quá nhỏ
  để có ý nghĩa.

Bản triển khai chọn cách diễn giải nhất quán về số học: **chế độ `risk`** — mỗi Unit
được định cỡ sao cho khi chạm stop 2N, tài khoản mất đúng `risk_per_unit` (mặc định
1%). Kèm theo trần cứng 20% NAV/Unit và 60% NAV/mã. Hệ quả thực tế: một Unit thường
chiếm 15–20% NAV.

### 3.3 Chi phí giao dịch

| Thành phần | Giá trị |
|---|---|
| Phí môi giới | 0,15% mỗi chiều |
| Thuế TNCN khi bán | 0,10% giá trị bán |
| Trượt giá | 0,10% mỗi chiều |
| Lô chẵn | 100 cổ phiếu |
| Margin | Không dùng |

Tổng chi phí khứ hồi ≈ 0,60% giá trị lệnh. Với tần suất 1 lệnh/năm/mã, chi phí
không đáng kể; với 16 lệnh/năm ở cấp danh mục, chi phí bắt đầu có ý nghĩa.

---

## 4. Hàm mục tiêu và thuật toán di truyền

### 4.1 Hàm mục tiêu kép

```
Fitness = w₁ × clip(Calmar, −3, 8) − w₂ × |MaxDD| − phạt_tần_suất

Calmar = CAGR / |MaxDD|
w₁ = 0,7 ; w₂ = 0,3
```

Số hạng phạt:

```
nếu lệnh/năm < 2   : phạt = penalty_weight × (2 − lệnh/năm) / 2
nếu lệnh/năm > 20  : phạt = penalty_weight × (lệnh/năm − 20) / 20
ngược lại          : phạt = 0
```

Việc cắt biên Calmar trong [−3, 8] ngăn một fold may mắn chi phối quần thể. Số hạng
phạt hiện thực hoá yêu cầu "tần suất giao dịch trung bình": nghiệm quá thưa (thiếu ý
nghĩa thống kê) và nghiệm quá dày (chi phí ăn mòn) đều bị trừ điểm.

### 4.2 Toán tử di truyền

| Thành phần | Lựa chọn |
|---|---|
| Genome | 5 gen: `entry_window` (40–70), `exit_window` (15–25), `atr_period` (14–25), `risk_per_unit` (0,5–1,5%), `stop_atr` (1,5–3,0) |
| Khởi tạo | Ngẫu nhiên đều trên không gian; cá thể đầu tiên neo tại Donchian-55 |
| Chọn lọc | Tournament, k = 3 |
| Lai ghép | BLX-α, α = 0,35, xác suất 0,85 |
| Đột biến | Gaussian với σ thu hẹp dần (hệ số 0,15 → 0,03), xác suất 0,18/gen; 8% khả năng tái sinh hoàn toàn gen |
| Tinh hoa | 4 cá thể mỗi thế hệ |
| Dừng sớm | Sau `max(8, generations/3)` thế hệ không cải thiện |
| Hạt giống | `seed = 20240101 + chỉ số fold` — bảo đảm tái lập |

> **Bài học vận hành.** Ngữ cảnh đánh giá của GA là một biến toàn cục của tiến trình
> (nhằm tránh pickle `FeatureBank` hơn 100 MB cho mỗi genome). Một bản triển khai
> trước đây chỉ nạp ngữ cảnh khi biến đó rỗng, nên từ lần gọi `run_ga` thứ hai trở đi
> GA vẫn tối ưu trên cửa sổ ngày của lần gọi đầu. Hậu quả: toàn bộ 3.800 fold
> walk-forward trả về đúng một bộ tham số và trông như "GA không bao giờ cải thiện
> được gì". Ngữ cảnh nay được nạp lại ở **mọi** lần gọi, và có test hồi quy
> (`test_run_ga_refreshes_context_between_calls`) khoá hành vi này.

### 4.3 Hàm gộp nhiều mã

GA trên rổ mã cần một điểm số duy nhất từ 100 mã. Ba lựa chọn:

- `median` — bền với outlier nhưng **mất gradient** khi hơn nửa rổ không phát sinh
  lệnh (đúng tình huống của bộ lọc ADV 30 tỷ giai đoạn 2016–2020: trung vị bằng 0
  với mọi bộ tham số, GA không có hướng tiến hoá).
- `mean` — có gradient nhưng bị vài mã cực đoan chi phối.
- `trimmed` — **mặc định**: trung bình sau khi cắt 10% đuôi mỗi phía. Giữ gradient,
  kháng outlier.

### 4.4 Song song hoá

`FeatureBank` nặng khoảng 130 MB với 100 mã (54 mảng chỉ báo × 2.689 phiên × 100 cột).
Nếu truyền kèm mỗi tác vụ, chi phí pickle sẽ lấn át toàn bộ thời gian tính toán. Mọi
pool đều nạp ngữ cảnh **một lần** qua `ProcessPoolExecutor(initializer=…)`; tác vụ chỉ
truyền genome hoặc mã. Walk-forward song song theo **mã** (mỗi tiến trình xử lý trọn
một mã, tránh tranh chấp dữ liệu).

---

## 5. Quy trình kiểm định

### 5.1 Kiểm định out-of-sample theo mã

- Fit: 70% dữ liệu đầu (khoảng 1.882 phiên, 2016 → giữa 2023).
- Test: 30% dữ liệu cuối (khoảng 807 phiên, giữa 2023 → 2026).
- Cổng chấp nhận: **Calmar(OOS) > 0,5** và **lệnh/năm < 20** và có phát sinh lệnh.
- Song song đó chạy cùng cổng với tham số mặc định Donchian-55 để đo **lợi thế thật
  của GA**, không chỉ đo kết quả tuyệt đối.

### 5.2 Walk-forward 252/63

```
fit 252 phiên  →  test 63 phiên  →  dịch 63 phiên  →  lặp lại
```

Với khoảng 2.689 phiên, mỗi mã sinh khoảng 39 fold. Báo cáo **phân phối** trên toàn
bộ fold — không chỉ một con số tổng hợp.

**Vì sao thước đo chính là lợi nhuận của chính cửa sổ test, không phải Calmar.**
Calmar = CAGR / |MaxDD|. Trên cửa sổ test chỉ 63 phiên, tử số là CAGR nội suy từ ba
tháng còn mẫu số là một MaxDD rất nhỏ; tỷ số này dao động cực mạnh và có thể đạt
−2 hoặc +5 chỉ vì mẫu số vài phần trăm. Trung vị Calmar trên 985 fold có giao dịch
là −2,39 — con số này nói về phương sai của thước đo nhiều hơn là về chiến lược.
Vì vậy:

- Thước đo chính: **lợi nhuận tích luỹ của 63 phiên test** (`total_return`), cùng
  **tỷ lệ fold có lãi**.
- Calmar vẫn được báo cáo nhưng chỉ để đối chiếu với cổng chấp nhận của đặc tả.

**Vì sao phải tách phân phối có điều kiện.** Bộ lọc ADV 30 tỷ chặn gần như toàn bộ
tín hiệu giai đoạn 2016–2020, nên phần lớn fold kết thúc với đường vốn phẳng: Calmar
và Sharpe bằng đúng 0 vì không có lệnh nào. Phân phối trên mọi fold vì thế chỉ là
một cột spike tại 0. Báo cáo này công bố đồng thời hai phân phối: trên mọi fold và
trên các fold **thực sự phát sinh giao dịch** (`distributions_traded`), kèm tỷ lệ
fold có giao dịch để người đọc biết mình đang so sánh trên bao nhiêu quan sát.

### 5.3 Kiểm định theo danh mục

Mô phỏng danh mục chia sẻ một tài khoản tiền mặt:

- Vốn khởi điểm 1 tỷ VND, không dùng margin.
- Tối đa 5 mã đồng thời, tổng giải ngân ≤ 60% NAV, dự phòng tiền mặt 5% NAV.
- Tối đa 2 vị thế mới mỗi phiên, ứng viên xếp hạng theo độ mạnh breakout
  (`close/upper − 1`).

Đây là cấu hình gần với thực tế vận hành nhất, và là nơi tần suất giao dịch đạt
6–17 lệnh/năm — khớp với yêu cầu "tần suất trung bình" của đặc tả.

### 5.4 Phân tích loại bỏ (ablation)

Chín kịch bản, mỗi kịch bản tắt đúng một ràng buộc, để đo đóng góp riêng của nó:

| Khoá | Thay đổi |
|---|---|
| `full` | Đầy đủ (mốc so sánh) |
| `no_market_filter` | Bỏ lọc VN-Index > SMA200 |
| `adv_10bn` | Hạ ngưỡng ADV xuống 10 tỷ |
| `no_adv_filter` | Bỏ hẳn lọc ADV |
| `no_ceiling_rule` | Cho phép vào lệnh tại giá trần |
| `no_t2_lock` | Bỏ khoá T+2.5 |
| `no_pyramid` | Không gia tăng Unit (1 Unit/mã) |
| `s1_fast` | Turtle S1 (entry 20, exit 10) |
| `unfiltered` | Bỏ toàn bộ bộ lọc |

### 5.5 Tái lập và kiểm thử

```bash
python -m pytest tests -q        # 55 test, không cần mạng
```

Bộ test tập trung vào những chỗ dễ sai âm thầm và khó phát hiện bằng mắt trên biểu đồ:

| Nhóm | Nội dung khoá |
|---|---|
| Chỉ báo | Bước giá và biên độ giá trần/sàn theo từng khung giá HOSE; ATR Wilder có mồi SMA; Donchian loại trừ phiên hiện tại |
| Toàn vẹn dữ liệu | `np.roll` phải có `axis=0`; chỉ báo của các mã không được trộn cột; mã niêm yết muộn không bị NaN vĩnh viễn |
| Ràng buộc Việt Nam | Khoá T+2.5 chặn stop trong 2 phiên đầu; breakout tại giá trần bị bỏ; thoát lệnh treo khi kẹt sàn; lọc ADV và lọc xu hướng chặn đúng |
| Kế toán | Vốn cuối kỳ = vốn đầu kỳ + tổng lãi/lỗ các lệnh; tiền mặt không âm; trần tỷ trọng áp đúng tại thời điểm vào lệnh |
| GA | Genome luôn nằm trong biên; `exit_window < entry_window`; tái lập theo hạt giống; fitness tốt nhất đơn điệu; **ngữ cảnh đánh giá được nạp lại giữa các lần gọi** |
| Walk-forward | Bước dịch cửa sổ; fold cuối nằm gọn trong dữ liệu; thống kê phân phối |

---

## 6. Giới hạn phương pháp luận

1. **Survivorship bias.** Danh sách VN100 lấy tại thời điểm chạy, không point-in-time
   theo từng kỳ tái cơ cấu. Các mã bị loại khỏi rổ trong quá khứ không có mặt trong
   mẫu, khiến kết quả có xu hướng lạc quan hơn thực tế.
2. **Cổ tức tiền mặt và quyền mua.** Giá đã điều chỉnh nhưng dòng cổ tức tiền mặt
   không được cộng vào đường vốn, cũng không mô hình hoá quyền mua phát hành thêm.
3. **Khớp tại giá đóng cửa.** Tín hiệu xác định bằng giá đóng cửa và khớp luôn tại giá
   đóng cửa cộng trượt giá. Trên thực tế lệnh phải đặt trước phiên ATC — đây là giả
   định lạc quan nhẹ, đã bù một phần bằng slippage 0,10%.
4. **Không mô hình hoá độ sâu sổ lệnh.** Không xét xếp hàng tại giá trần/sàn, không
   xét việc lệnh không khớp khi thanh khoản cạn, không xét ảnh hưởng thị trường của
   chính lệnh.
5. **Slippage cố định.** Không phụ thuộc ADV hay biến động — xem mục 2.4.
6. **Một tài sản, một chiều.** Chỉ cổ phiếu cơ sở, chỉ long. Không phái sinh phòng hộ.
7. **Rủi ro overfitting.** GA trên dữ liệu quá khứ luôn có nguy cơ này. Ba lớp giảm
   thiểu: OOS 30%, walk-forward, cổng chấp nhận. Khoảng cách Calmar trong mẫu và
   ngoài mẫu được hiển thị công khai chứ không che đi.
8. **Tính phi dừng.** Thị trường Việt Nam đã đổi cấu trúc nhiều lần trong 2016–2026
   (hệ thống KRX, biên độ, lô chẵn, các chu kỳ margin call 2018 và 2022). Một bộ tham
   số cố định không thể bao quát mọi chế độ thị trường.

---

## 7. Kết quả mong đợi và cách đọc

Khi đọc website, thứ tự quan trọng:

1. **Tab Tổng quan** — đường vốn danh mục so với VN-Index, phân phối Calmar/Sharpe
   theo mã. Đây là bức tranh tổng thể.
2. **Tab Walk-forward** — phân phối ngoài mẫu. Nếu phân phối lệch về 0 hoặc âm, chiến
   lược không có edge bền vững bất kể kết quả trong mẫu đẹp thế nào.
3. **Tab Đặc thù Việt Nam** — bảng ablation. Đây là nơi trả lời câu hỏi "ràng buộc nào
   thực sự quan trọng".
4. **Tab Tối ưu GA** — so sánh GA với tham số mặc định. Nếu lợi thế của GA biến mất
   ngoài mẫu, kết luận đúng là GA đang overfit chứ không phải đang tối ưu.
5. **Tab Danh mục** — nhật ký giao dịch và lợi nhuận theo tháng, để thấy mức độ tập
   trung lợi nhuận theo thời gian.

Kết quả của một chiến lược breakout theo xu hướng thường có dạng: nhiều năm đi ngang
hoặc lỗ nhẹ, vài năm bùng nổ. Nếu đường vốn tăng đều đặn mỗi tháng, gần như chắc chắn
có lỗi look-ahead hoặc overfitting.
