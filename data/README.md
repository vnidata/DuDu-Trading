# Thư mục dữ liệu

| Tệp / thư mục | Được commit? | Nội dung |
|---|---|---|
| `manifest.json` | Có | Bản kê universe: số mã, số phiên, khoảng ngày, danh sách mã thiếu |
| `universe_VN100.json` | Có | Danh sách thành phần VN100 tại thời điểm tải, kèm URL nguồn |
| `raw/` | Không | OHLCV từng mã, CSV nén (`{MÃ}_{NĂM}.csv.gz`) |

## Tái tạo dữ liệu

```bash
python scripts/fetch_data.py --group VN100 --start 2016-01-01
```

Lệnh này tự bỏ qua các mã đã có cache còn mới (mặc định 3 ngày) và tự điều tiết
nhịp gọi API xuống 48 request/phút. Nếu chạm trần rate limit của nhà cung cấp,
tiến trình dừng mềm và chỉ cần chạy lại là tiếp tục từ chỗ còn thiếu.

Thêm `--refresh` để tải lại toàn bộ bất kể cache.

## Nguồn và tính bất biến

- Nguồn: Vnstock 3.x, nhà cung cấp VCI (Vietcap).
- Giá đã được điều chỉnh cổ tức và chia tách.
- Danh sách VN100 là ảnh chụp tại thời điểm chạy, **không phải point-in-time** —
  xem mục "Giới hạn phương pháp luận" trong `METHODOLOGY.md`.

Vì `raw/` không được commit, mọi kết quả trong `site/data/` chỉ tái lập được nếu
tải lại đúng khoảng thời gian. Chênh lệch nhỏ về dữ liệu giữa các thời điểm chạy
là điều bình thường với dữ liệu thị trường cập nhật hằng ngày.
