# DuDu-Trading

**Donchian Breakout (Turtle System 2) × Genetic Algorithm cho thị trường chứng khoán Việt Nam**

Bộ công cụ nghiên cứu định lượng + website tĩnh (GitHub Pages) triển khai chiến lược
phá đỉnh Donchian trên rổ VN100, tối ưu tham số bằng thuật toán di truyền, sử dụng dữ liệu
[Vnstock](https://github.com/thinh-vu/vnstock) (nguồn VCI – Vietcap).

Website: `site/index.html` — mở trực tiếp bằng trình duyệt hoặc xem qua GitHub Pages.

---

## 0. Kết quả chính (đọc trước)

Rổ VN100, 100 mã, 2.689 phiên từ 2016-01-04 đến 2026-10-09, vốn 1 tỷ VND, không margin,
chi phí giao dịch đầy đủ (phí 0,15%/chiều, thuế bán 0,10%, trượt giá 0,10%/chiều).

| Chỉ số | Danh mục Donchian-55 | Tham số GA trên rổ | VN-Index mua-và-giữ |
|---|---|---|---|
| CAGR | +9,7% | +6,4% | **+10,9%** |
| Sharpe | 0,60 | 0,47 | **0,65** |
| MaxDD | **−49,5%** | −37,1% | −45,3% |
| Calmar | 0,20 | 0,17 | **0,24** |
| Số lệnh/năm | 17,1 | 32,1 | — |

Bốn kết luận định lượng, tất cả đều bất lợi cho giả thuyết ban đầu của đặc tả:

1. **Thua mua-và-giữ.** Danh mục kém VN-Index 1,2 điểm phần trăm CAGR, Sharpe thấp hơn và
   drawdown sâu hơn. Đây là so sánh chưa cộng cổ tức tiền mặt cho chỉ số, tức chỉ số còn
   được lợi thêm.
2. **GA không tạo giá trị ngoài mẫu.** GA theo từng mã cho Calmar OOS trung vị **−0,065**
   so với **−0,034** của tham số mặc định — tức GA làm kết quả ngoài mẫu **tệ hơn 0,030**.
   Chỉ 7/100 mã đạt cổng chấp nhận. Khoảng cách trong mẫu/ngoài mẫu trung vị là 0,139:
   dấu hiệu overfitting điển hình.
3. **Walk-forward xác nhận.** Trên 3.800 fold, chỉ 26,2% fold phát sinh giao dịch; trong số
   đó lợi nhuận 63 phiên test trung vị là **−0,84%** và chỉ **27,6%** fold có lãi. Tỷ lệ đạt
   cổng Calmar > 0,5 là 6,7% trên mọi fold (25,6% nếu chỉ tính fold có giao dịch). Chênh lệch
   lợi nhuận test giữa GA và mặc định là **−0,09 điểm phần trăm** — GA không hơn gì.
4. **Bộ lọc thanh khoản là nút thắt.** Ngưỡng ADV 30 tỷ VND/phiên chỉ đạt **2,6% số quan sát
   năm 2016** và mở dần tới **78,8% năm 2025**. Trong 5 năm đầu, chiến lược gần như không
   giao dịch: phần lớn "kết quả" của giai đoạn đó chỉ là đường vốn phẳng, không phải hiệu suất
   hoà vốn. Nới ngưỡng xuống 10 tỷ đưa Calmar trung vị từ 0,00 lên 0,04; bỏ hẳn lọc lên 0,08.

Mã nguồn, engine và hạ tầng đo lường đều hoạt động đúng; thứ không đứng vững là **giả thuyết
có edge**. Repo công bố cả những con số này thay vì chỉ chọn cấu hình đẹp nhất. Cách đọc và
toàn bộ giả định nằm trong [`METHODOLOGY.md`](METHODOLOGY.md).

---

## 1. Vì sao Donchian Breakout

Thị trường Việt Nam có bốn đặc thù vi cấu trúc định hình lựa chọn chiến lược:

| Đặc thù | Hệ quả thiết kế |
|---|---|
| Biên độ ±7% và giá trần/sàn | Không vào lệnh khi đóng cửa tại giá trần; treo lệnh thoát khi kẹt giá sàn |
| Chu kỳ thanh toán T+2.5 | Cổ phiếu mua tại t chỉ bán được từ t+2; mỗi Unit mới bị khoá 2 phiên trước khi stop có hiệu lực |
| Cấm bán khống cổ phiếu cơ sở | Engine long-only tuyệt đối |
| Thanh khoản phân tán | Lọc ADV 20 phiên ≥ 30 tỷ VND và trần tỷ trọng NAV |

Trong nhóm chiến lược phù hợp, nhóm theo xu hướng (breakout) có lợi thế cấu trúc: hit rate
thấp nhưng payoff cao, chịu được nhiễu và không đòi hỏi dự báo đảo chiều — vốn là điểm yếu
của các chiến lược mean-reversion trên thị trường có xu hướng mạnh và hay bị margin call
theo cụm.

## 2. Cấu trúc chiến lược

| Tham số | Mặc định | Vai trò |
|---|---|---|
| `entry_window` | 55 phiên | Đóng cửa vượt đỉnh 55 phiên (không tính ngày hiện tại) → mua |
| `exit_window` | 20 phiên | Đóng cửa dưới đáy 20 phiên → thoát |
| `atr_period` | 20 phiên | N = ATR Wilder |
| `stop_atr` | 2.0 N | Stop loss dưới giá vào của Unit mới nhất |
| `pyramid_atr` | 0.5 N | Gia tăng 1 Unit mỗi 0.5N thuận lợi, tối đa 4 Unit |
| `risk_per_unit` | 1% vốn | Lỗ đúng 1% vốn khi chạm stop (chế độ `risk`) |

Công thức position sizing:

```
Unit = (risk_per_unit × Equity) / (stop_atr × N)     # chế độ "risk" (mặc định)
Unit = (risk_per_unit × Equity) / N                  # chế độ "volatility" — Turtle gốc
```

> **Điểm phải diễn giải lại đặc tả gốc.** Với N ≈ 3% giá, công thức Turtle gốc cho mỗi Unit
> chiếm ~33% NAV, tức 4 Unit vượt 130% NAV — không khả thi khi không dùng margin và trần
> exposure 60%. Bản triển khai dùng chế độ `risk` và áp thêm trần cứng 20% NAV/Unit,
> 60% NAV/mã. Đây là mâu thuẫn số học trong đặc tả ("mỗi Unit chiếm 5–7% NAV" so với
> công thức `1%×Equity/(ATR×Giá)`) và đã được xử lý tường minh.

## 3. Cài đặt

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

Yêu cầu: Python ≥ 3.10. `truststore` là bắt buộc trong mạng nội bộ có proxy chèn chứng thư
gốc (Kaspersky/BIDV CA) — nếu không, mọi request HTTPS tới API dữ liệu sẽ báo
`CERTIFICATE_VERIFY_FAILED`.

## 4. Chạy pipeline

```bash
python scripts/fetch_data.py --group VN100 --start 2016-01-01   # tải và cache OHLCV
python scripts/run_research.py --jobs 10                         # chạy toàn bộ nghiên cứu
python scripts/build_site.py                                     # đồng bộ site/ -> docs/ (GitHub Pages)
```

Chạy thử nhanh:

```bash
python scripts/run_research.py --limit 12 --fast --no-walkforward
```

### Lưu ý về giới hạn API

Thư viện `vnai` đi kèm vnstock áp trần **60 request/phút** cho nguồn VCI và gọi thẳng
`sys.exit()` khi vượt trần. Pipeline tự điều tiết xuống **48 request/phút** bằng
`dudu.data.RateLimiter` và dừng mềm (`DataFetchInterrupted`) để lần chạy sau tiếp tục từ cache.

## 5. Cập nhật tự động 5 phút & Nguồn cấp dữ liệu thời gian thực

Hệ thống hỗ trợ cập nhật dữ liệu tự động **mỗi 5 phút trong phiên giao dịch HOSE** (09:00 - 15:00 giờ Việt Nam) với nguồn cấp dữ liệu kép:
- **Nguồn cấp trực tuyến thời gian thực (Primary)**: VNDirect DChart API (<200ms/mã, SSL bypass, nến ngày và intraday thời gian thực).
- **Tầng kết nối MCP (Model Context Protocol)**: Hỗ trợ SSI, DNSE, VCBS qua JSON-RPC 2.0 (`dudu/mcp_client.py`).
- **Nguồn dữ liệu dự phòng**: Vietcap (VCI) qua vnstock 3.x với RateLimiter điều tiết 48 req/phút.

Workflow GitHub Actions (`.github/workflows/update-data.yml`) kích hoạt:
- `cron: "*/5 2-8 * * 1-5"`: Cập nhật ảnh chụp thị trường và tín hiệu mỗi 5 phút trong phiên.
- `cron: "0 8 * * 1-5"`: 15:00 VN chốt phiên, kích hoạt pipeline nghiên cứu đầy đủ (GA + walk-forward).
- `cron: "0 22 * * 5"`: 05:00 VN thứ Bảy bản làm sâu cuối tuần.

Client web dashboard tích hợp cơ chế tự động polling mỗi 5 phút với cache-busting `?_t=...`, đồng hồ đếm ngược từng giây và nút làm mới dữ liệu tức thì.

### Ba điều cần biết trước khi tin vào con số trong phiên

1. **Cron của GitHub Actions không đúng phút.** Vào giờ cao điểm, workflow theo lịch có thể
   trễ 5–30 phút hoặc bị bỏ qua. Đây là giới hạn GitHub đã ghi nhận, không phải lỗi cấu hình.
   Website hiển thị nhãn "cập nhật N phút trước" để người đọc tự đánh giá độ tươi.
2. **Trong phiên, bar ngày chưa hoàn tất.** Giá đóng cửa chỉ là giá khớp gần nhất nên tín hiệu
   có thể đảo chiều trước khi phiên kết thúc. Trường `is_final` đánh dấu rõ và website hiện
   cảnh báo vàng khi bar chưa chốt.
3. **Workflow theo lịch tự tạm dừng sau 60 ngày repo không có hoạt động.** Commit tự động của
   chính workflow được tính là hoạt động nên vòng lặp này tự nuôi nhau; nhưng nếu dữ liệu ngừng
   đổi trong 60 ngày (ví dụ nguồn lỗi), lịch sẽ dừng và cần bật lại thủ công.

Có thể chạy tay bất cứ lúc nào:

```bash
python scripts/snapshot.py                       # ngưỡng cache 5 phút
python scripts/snapshot.py --refresh             # buộc tải lại toàn bộ
python scripts/snapshot.py --offline             # chỉ đọc cache, không gọi mạng
python scripts/snapshot.py --at "2026-10-12T10:00:00+07:00"   # mô phỏng một mốc giờ
```

## 6. Kiến trúc mã nguồn

```
dudu/
  config.py       Cấu hình vi cấu trúc thị trường, tham số chiến lược, không gian GA
  data.py         Universe VCI, tải OHLCV vnstock, cache CSV nén, điều tiết rate limit
  indicators.py   Donchian, ATR Wilder, SMA, giá trần/sàn, FeatureBank tính trước
  backtest.py     Engine sự kiện một mã + mô phỏng danh mục chia sẻ vốn
  metrics.py      CAGR, Sharpe, Sortino, MaxDD, Calmar, R-multiple, hit rate
  ga.py           Genetic Algorithm: genome, fitness kép, BLX-α, tournament, elitism
  walkforward.py  Walk-forward 252/63, cổng kiểm định out-of-sample
  snapshot.py     Ảnh chụp thị trường trong phiên, nhãn phiên HOSE, lịch sử rút gọn
  pipeline.py     Điều phối 7 bước + ablation + quét lưới tham số
  report.py       Kết xuất JSON cho website
scripts/          fetch_data, run_research, snapshot, rebuild_walkforward, refresh_meta,
                  build_site, check_site.js, smoke_dom.js
site/             Website tĩnh (HTML/CSS/JS, Chart.js CDN)
tests/            Kiểm thử đơn vị cho engine, metrics, GA, dữ liệu, ảnh chụp phiên
```

## 7. Kiểm thử

```bash
python -m pytest tests -q          # 79 test, không cần mạng
node scripts/check_site.js         # đối chiếu id/canvas/JSON giữa HTML và JS
node scripts/smoke_dom.js          # chạy app.js trên DOM giả với dữ liệu thật
```

Bộ Python bao phủ: giá trần/sàn theo bước giá HOSE, ATR Wilder có mồi SMA, ràng buộc T+2.5,
luật tránh giá trần, tính bất biến của engine theo cột dữ liệu (lỗi `np.roll` không `axis`
từng làm trộn chỉ báo giữa các mã), tái lập của GA theo hạt giống, và nhãn phiên HOSE theo
từng mốc giờ. Smoke test DOM bắt các lỗi runtime mà kiểm tra tĩnh không thấy.

## 8. Giới hạn phương pháp luận

- **Survivorship bias**: danh sách VN100 lấy tại thời điểm chạy, không phải point-in-time.
- **Giá điều chỉnh**: dữ liệu VCI đã điều chỉnh cổ tức/chia tách; không mô hình hoá cổ tức tiền mặt.
- **Khớp tại giá đóng cửa**: giả định lạc quan nhẹ, bù bằng trượt giá 0,10% mỗi chiều.
- **Slippage cố định**: không phụ thuộc ADV, nên kết quả của các mã thanh khoản thấp có xu
  hướng bị đánh giá cao hơn thực tế. Đây là lý do phải đọc kèm bảng ablation.
- **Ngưỡng ADV tuyệt đối**: 30 tỷ VND/phiên chỉ đạt 2,6% số quan sát năm 2016 và mở dần tới
  ~75% năm 2024, khiến tần suất giao dịch giai đoạn đầu rất thấp. Báo cáo công khai hiện
  tượng này thay vì chọn ngưỡng theo kết quả.

Chi tiết đầy đủ trong [`METHODOLOGY.md`](METHODOLOGY.md).

## 9. Miễn trừ trách nhiệm

Đây là công cụ nghiên cứu và giáo dục. Không phải khuyến nghị đầu tư. Kết quả quá khứ không
bảo đảm cho tương lai.

Giấy phép: MIT.
