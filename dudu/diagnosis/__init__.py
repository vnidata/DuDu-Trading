"""Module Chẩn Đoán Sức Khỏe Cổ Phiếu Định Lượng (Stock Health Diagnosis).

Bao gồm:
- StockDoctor: Bác sĩ định lượng khám toàn diện kỹ thuật và ý kiến Hội đồng AI
- StockDiagnosisReport: Báo cáo chẩn đoán 360 độ kèm khuyến nghị hành động
"""

from .stock_doctor import StockDoctor, StockDiagnosisReport

__all__ = ["StockDoctor", "StockDiagnosisReport"]
