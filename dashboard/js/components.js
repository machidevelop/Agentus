/**
 * UI Component generators and modal layout renderers.
 */

class UIComponents {
  static formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
  }

  static renderOpportunityCard(item, onClick) {
    const card = document.createElement('div');
    card.className = 'opportunity-item';
    card.dataset.id = item.opportunity_id;

    const typeLabel = item.opportunity_type.replace(/_/g, ' ');
    const confLevel = item.confidence_level || 'medium';
    const confScore = (item.confidence_score * 100).toFixed(0);

    card.innerHTML = `
      <div class="opp-main-info">
        <div class="opp-header-row">
          <span class="badge badge-${item.opportunity_type}">${typeLabel}</span>
          <span class="badge conf-badge-${confLevel}">${confLevel.toUpperCase()} (${confScore}%)</span>
          <span class="opp-title">${item.title}</span>
        </div>
        <div class="opp-desc">${item.description}</div>
      </div>
      <div class="opp-metrics">
        <div class="opp-value-block">
          <div class="opp-value-monthly">+${UIComponents.formatCurrency(item.monthly_value)}/mo</div>
          <div class="opp-value-annual">Annual: ${UIComponents.formatCurrency(item.annual_value)}</div>
        </div>
        <button class="btn btn-secondary btn-sm">View Detail</button>
      </div>
    `;

    card.addEventListener('click', () => onClick(item.opportunity_id));
    return card;
  }

  static renderOpportunityDetail(detail) {
    const typeLabel = (detail.opportunity_type || '').replace(/_/g, ' ');
    const conf = detail.confidence || {};
    const comp = detail.impact || {};
    const delta = comp.delta || {};
    const val = detail.value || {};
    const alt = detail.alternative || {};

    return `
      <div class="detail-section">
        <h4>What Happened (Observed Decision X)</h4>
        <p class="opp-desc">${detail.what_happened}</p>
        <div class="grid-2col" style="margin-top:0.75rem;">
          <div class="metric-row"><span class="metric-label">Decision Time:</span><span class="metric-val">${new Date(detail.detected_at).toLocaleString()}</span></div>
          <div class="metric-row"><span class="metric-label">Affected Jobs:</span><span class="metric-val">${(detail.affected_job_ids || []).join(', ') || 'N/A'}</span></div>
          <div class="metric-row"><span class="metric-label">Observed GPUs:</span><span class="metric-val">${(detail.affected_gpu_ids || []).length} GPUs</span></div>
          <div class="metric-row"><span class="metric-label">Decision Type:</span><span class="metric-val">${(detail.decision || {}).decision_type || 'Allocate'}</span></div>
        </div>
      </div>

      <div class="detail-section">
        <h4>Feasible Alternative Action (Counterfactual Y)</h4>
        <p class="opp-desc" style="color:var(--accent-blue);">${alt.description || 'Agent proposed action'}</p>
        <p class="opp-desc" style="margin-top:0.4rem;"><strong>Agent Rationale:</strong> ${alt.rationale || 'N/A'}</p>
        <div class="grid-2col" style="margin-top:0.75rem;">
          <div class="metric-row"><span class="metric-label">Generator Method:</span><span class="metric-val">${alt.generation_method || 'Agent tool'}</span></div>
          <div class="metric-row"><span class="metric-label">Tools Invoked:</span><span class="metric-val">${(alt.tools_invoked || []).join(', ') || 'None'}</span></div>
        </div>
      </div>

      <div class="detail-section">
        <h4>Technical Impact & Metrics Delta (X vs Y)</h4>
        <div class="grid-2col">
          <div class="metric-row"><span class="metric-label">GPU-Hours Saved:</span><span class="metric-val">${(delta.gpu_hours_saved || 0).toFixed(2)} hrs</span></div>
          <div class="metric-row"><span class="metric-label">Utilization Lift:</span><span class="metric-val">+${(delta.utilization_improvement || 0).toFixed(1)}%</span></div>
          <div class="metric-row"><span class="metric-label">Idle Hours Recovered:</span><span class="metric-val">${(delta.idle_hours_recovered || 0).toFixed(2)} hrs</span></div>
          <div class="metric-row"><span class="metric-label">Queue Time Avoided:</span><span class="metric-val">${((delta.queue_time_reduction || 0) / 60).toFixed(0)} mins</span></div>
        </div>
      </div>

      <div class="detail-section">
        <h4>Observed vs Alternative GPU Utilization Timeline</h4>
        <div class="chart-container">
          <canvas id="utilChart"></canvas>
        </div>
      </div>

      <div class="detail-section" style="border-color:rgba(16,185,129,0.3);">
        <h4>Discovered Economic Value</h4>
        <div class="grid-2col">
          <div class="metric-row"><span class="metric-label">Direct Cost Avoided:</span><span class="metric-val">${UIComponents.formatCurrency(val.compute_cost_avoided || 0)}</span></div>
          <div class="metric-row"><span class="metric-label">Full-Time GPU Equivalent:</span><span class="metric-val">${(val.equivalent_gpus_recovered || 0).toFixed(2)} GPUs</span></div>
          <div class="metric-row"><span class="metric-label">Projected Monthly Value:</span><span class="metric-val" style="color:var(--accent-green);font-size:1.1rem;">${UIComponents.formatCurrency(val.estimated_monthly_value || 0)}</span></div>
          <div class="metric-row"><span class="metric-label">Projected Annual Value:</span><span class="metric-val" style="color:var(--accent-green);font-size:1.1rem;">${UIComponents.formatCurrency(val.estimated_annual_value || 0)}</span></div>
        </div>
        <p class="opp-desc" style="margin-top:0.6rem;font-size:0.8rem;color:var(--text-muted);">
          <strong>Assumptions Exposed:</strong> ${(val.assumptions || []).join('; ') || 'Standard cloud baseline costs.'}
        </p>
      </div>

      <div class="detail-section">
        <h4>Confidence Assessment & Rationale</h4>
        <div class="metric-row"><span class="metric-label">Composite Confidence Score:</span><span class="metric-val">${(conf.score || 0).toFixed(2)} (${(conf.level || 'medium').toUpperCase()})</span></div>
        <p class="opp-desc" style="margin-top:0.4rem;">${conf.explanation || ''}</p>
        <p class="opp-desc" style="margin-top:0.4rem;font-size:0.8rem;color:var(--accent-green);">
          ✓ Checked operational constraints: ${(conf.constraints_checked || []).join(', ') || 'All checked'}
        </p>
      </div>
    `;
  }
}
