# TÀI LIỆU CHUYỂN GIAO TOÀN DIỆN HỘI THOẠI & TRI THỨC DỰ ÁN
## Từ VN-Swing sang DuDu-Trading

> **Ngày chuyển giao:** 23/10/2026  
> **Dự án nguồn:** `vn-swing` (Kho: `https://github.com/vnidata/vn-swing`)  
> **Dự án đích:** `DuDu-Trading` (`E:\OneDrive\AI-Agent\DuDu-Trading` | Kho: `https://github.com/vnidata/DuDu-Trading`)  
> **Mục tiêu:** Kế thừa toàn bộ tri thức định lượng, pipeline dữ liệu, subagent kiểm thử QA và kiến trúc dashboard sang dự án DuDu-Trading.

---

### I. TÓM TẮT TIẾN TRÌNH & KẾT QUẢ ĐÃ ĐẠT ĐƯỢC

Trong suốt phiên hội thoại, hệ thống đã triển khai các cột mốc quan trọng sau:

#### 1. Nghiên cứu định lượng 3 phân kỳ (Institutional Quant Research)
- **Giai đoạn 1 (In-Sample: 2006 -> 31/12/2020):** Xây dựng không gian tham số và thử nghiệm 5 biến thể chiến lược theo đà (Trend Following).
- **Giai đoạn 2 (Out-of-Sample: 01/01/2021 -> 31/12/2024):** Kiểm định mô hình qua 4 chu kỳ thị trường khắc nghiệt (Uptrend 2021, Sụp đổ 2022, Phục hồi 2023, Đi ngang 2024).
  - **Mô hình Quán Quân (`V-DBO Trend Focus`):**
    - Đạt CAGR 4 năm: **+10.42%**, Sharpe OOS **0.36**, năm 2021 lãi **+74.71%**, năm 2022 phòng thủ giảm rủi ro, năm 2024 lãi **+13.23%**.
    - Tham số tối ưu: $N_{in}=30$ phiên, $N_{out}=15$ phiên, Volume $\ge 1.2 \times \text{SMA20}(V)$, Close Location Value (CLV) $\ge 0.50$, Relative Strength $RS \ge 0.50$ (Top 50%), Trailing Stop $3.0 \times \text{ATR}(14)$.
- **Giai đoạn 3 (Live Forward: 01/01/2025 -> Hiện tại):**
  - Chạy mô phỏng trên 107 lệnh đã đóng + 3 vị thế mở (tổng 110 lệnh).
  - Tỷ lệ thắng (Win Rate): **29.91%**, Profit Factor: **1.10**, Tổng lãi ròng thực tế: **+123,607,145 VND** (+12.36% NAV ban đầu 1 tỷ).
  - Bắt trúng các siêu cổ phiếu gánh toàn bộ các lệnh cắt lỗ nhỏ: VIC (+108.98%), SBT (+94.67%), SHB (+81.68%).
  - Đã xuất bản chi tiết sổ lệnh: `data/trade_history_2025_2026.json` & `.csv`.

#### 2. Xây dựng Website Dashboard Trực Tuyến & Tab Tra Cứu Lệnh
- Triển khai website giám sát tín hiệu định lượng tại: `https://vnidata.github.io/vn-swing/`
- Bổ sung Tab thứ 4: **Lịch Sử Lệnh & Hiệu Suất (2025 - Nay)** với 4 card KPI, bộ lọc nhanh (Tất cả, Đang mở, Lệnh lãi, Lệnh lỗ) và ô tìm kiếm mã cổ phiếu tương tác.
- Bổ sung trực quan hóa cấu trúc xu hướng chủ đạo của VN-Index đa khung thời gian (SMA20, SMA50, SMA100).

#### 3. Thiết lập Subagent Chuyên Trách: `qa-data-tester`
- Subagent chuyên trách kiểm thử tính năng (19 bài test Pytest) và tự động cập nhật, kiểm định chất lượng dữ liệu (0 Null/NaN, không vi phạm biên độ sàn HOSE, không rò rỉ tương lai).
- File đặc tả chuẩn ECC: `agents/qa-data-tester.md`.
- Script tự động hóa toàn diện: `scripts/run_qa_and_sync.py`.

#### 4. Nâng cấp chu kỳ đồng bộ dữ liệu Realtime lên 5 phút
- GitHub Actions tự động kích hoạt mỗi 5 phút: `cron: '*/5 2-8 * * 1-5'`.
- Nạp nến 1 phút mới nhất của VN-Index và cổ phiếu từ Entrade API.
- Chuẩn hóa múi giờ Việt Nam `Asia/Ho_Chi_Minh` (UTC+7) trên toàn bộ hệ thống.
- Khắc phục lỗi kẹt nến bằng cơ chế tự động mở rộng hàng nến realtime trong phiên.

---

### II. HIỆN TRẠNG & TƯƠNG QUAN VỚI DỰ ÁN `DuDu-Trading`

Dự án `DuDu-Trading` (`E:\OneDrive\AI-Agent\DuDu-Trading`) có mối quan hệ trực tiếp và chiều sâu nghiên cứu học thuật cao hơn:
1. **Bản chất chiến lược:**
   - Triển khai **Turtle System 2 (Donchian Breakout 55/20)** kết hợp **Thuật toán Di truyền (Genetic Algorithm - GA)** trên rổ VN100 (100 mã thanh khoản cao).
   - Kiểm định nghiêm ngặt: Walk-Forward Validation (3.800 fold), kiểm soát rủi ro T+2.5, giá trần/sàn, lọc thanh khoản ADV 30 tỷ/phiên.
2. **Bộ kiểm thử hiện có:**
   - Đã có **79 unit tests** đạt 100% PASS (`pytest tests/`).
3. **Kiến trúc Website & Snapshot:**
   - Thư mục `site/`: Dashboard trực quan hiển thị snapshot phiên giao dịch, độ rộng thị trường, tín hiệu vào/ra.
   - Script `scripts/snapshot.py`: Tự động ghi nhận ảnh chụp thị trường theo 6 mốc phiên HOSE (09:45, 10:00, 11:30, 13:30, 14:00, 15:00).
   - Workflow: `.github/workflows/update-data.yml`.

---

### III. KẾ HOẠCH HÀNH ĐỘNG TIẾP THEO TRÊN `DuDu-Trading`

1. **Khắc phục lỗi hiển thị tiếng Việt trên Console Windows:**
   - Thêm `sys.stdout.reconfigure(encoding="utf-8")` vào `scripts/snapshot.py` để tránh lỗi `UnicodeEncodeError` (CP1252).
2. **Đồng bộ cơ chế Realtime 5 phút & Nến Trong Phiên:**
   - Tích hợp kỹ thuật nạp nến phút Entrade và mở rộng hàng nến realtime đã giải quyết ở `vn-swing` vào module `dudu/data.py` và `scripts/snapshot.py`.
3. **Triển khai Subagent `qa-data-tester` cho DuDu-Trading:**
   - Tích hợp `agents/qa-data-tester.md` để tự động chạy 79 bài test và kiểm tra dữ liệu cache rổ VN100.
4. **Kiểm tra và Deploy Website GitHub Pages:**
   - Build và xuất bản website của `DuDu-Trading` lên GitHub Pages repo `https://github.com/vnidata/DuDu-Trading.git`.

---

*Tài liệu này được sinh tự động để đảm bảo tính liên tục 100% của phiên làm việc khi chuyển đổi dự án.*
