/**
 * Canvas timeline chart component for observed vs counterfactual GPU utilization.
 */

class UtilizationChart {
  static render(canvas, series) {
    if (!canvas || !series || series.length === 0) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width = canvas.parentElement.clientWidth || 600;
    const height = canvas.height = canvas.parentElement.clientHeight || 200;

    ctx.clearRect(0, 0, width, height);

    const padding = { top: 20, right: 30, bottom: 30, left: 40 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    // Draw Grid
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    ctx.lineWidth = 1;
    for (let y = 0; y <= 100; y += 25) {
      const py = padding.top + chartH - (y / 100) * chartH;
      ctx.beginPath();
      ctx.moveTo(padding.left, py);
      ctx.lineTo(width - padding.right, py);
      ctx.stroke();

      ctx.fillStyle = '#6b7280';
      ctx.font = '10px Inter';
      ctx.textAlign = 'right';
      ctx.fillText(`${y}%`, padding.left - 8, py + 3);
    }

    const pointsCount = series.length;
    const stepX = chartW / Math.max(1, pointsCount - 1);

    // Plot Actual Observed Line (Red / Amber)
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 2;
    ctx.beginPath();
    series.forEach((pt, i) => {
      const x = padding.left + i * stepX;
      const y = padding.top + chartH - (pt.actual_pct / 100) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Plot Alternative Counterfactual Line (Green / Blue)
    ctx.strokeStyle = '#10b981';
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    series.forEach((pt, i) => {
      const altPct = pt.alternative_pct != null ? pt.alternative_pct : pt.actual_pct;
      const x = padding.left + i * stepX;
      const y = padding.top + chartH - (altPct / 100) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);

    // Legend
    ctx.font = '11px Inter';
    ctx.textAlign = 'left';

    ctx.fillStyle = '#ef4444';
    ctx.fillRect(width - 220, 10, 12, 3);
    ctx.fillStyle = '#9ca3af';
    ctx.fillText('Observed Decision (X)', width - 200, 14);

    ctx.fillStyle = '#10b981';
    ctx.fillRect(width - 100, 10, 12, 3);
    ctx.fillStyle = '#9ca3af';
    ctx.fillText('Alternative (Y)', width - 80, 14);
  }
}
