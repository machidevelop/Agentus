/**
 * Main Natilah Dashboard Application Controller.
 */

document.addEventListener('DOMContentLoaded', () => {
  let opportunitiesData = [];

  // DOM Elements
  const kpiGpus = document.getElementById('kpiGpus');
  const kpiDecisions = document.getElementById('kpiDecisions');
  const kpiOpportunities = document.getElementById('kpiOpportunities');
  const kpiHours = document.getElementById('kpiHours');
  const kpiEquivGpus = document.getElementById('kpiEquivGpus');
  const kpiMonthly = document.getElementById('kpiMonthly');
  const kpiAnnual = document.getElementById('kpiAnnual');

  const opportunityList = document.getElementById('opportunityList');
  const filterType = document.getElementById('filterType');
  const filterConfidence = document.getElementById('filterConfidence');

  const btnGenerate = document.getElementById('btnGenerate');
  const btnRunAnalysis = document.getElementById('btnRunAnalysis');
  const btnCostConfig = document.getElementById('btnCostConfig');

  const opportunityModal = document.getElementById('opportunityModal');
  const modalClose = document.getElementById('modalClose');
  const modalBody = document.getElementById('modalBody');
  const modalTitle = document.getElementById('modalTitle');
  const modalTypeBadge = document.getElementById('modalTypeBadge');

  const costModal = document.getElementById('costModal');
  const costModalClose = document.getElementById('costModalClose');
  const costCancel = document.getElementById('costCancel');
  const costForm = document.getElementById('costForm');

  // Load Dashboard Data
  async function loadDashboard() {
    try {
      const summary = await NatilahAPI.getSummary();
      kpiGpus.textContent = summary.gpus_analyzed.toLocaleString();
      kpiDecisions.textContent = summary.decisions_analyzed.toLocaleString();
      kpiOpportunities.textContent = summary.opportunities_found.toLocaleString();
      kpiHours.textContent = `${summary.gpu_hours_recovered.toFixed(1)} hrs`;
      kpiEquivGpus.textContent = `${summary.equivalent_gpus.toFixed(2)} Equivalent GPUs`;
      kpiMonthly.textContent = UIComponents.formatCurrency(summary.monthly_value);
      kpiAnnual.textContent = `Annual: ${UIComponents.formatCurrency(summary.annual_value)}`;

      opportunitiesData = await NatilahAPI.getOpportunities();
      renderFeed();
    } catch (err) {
      console.error('Failed to load dashboard:', err);
      opportunityList.innerHTML = `<div class="loading-state"><p style="color:var(--accent-red)">Failed to load data: ${err.message}</p></div>`;
    }
  }

  // Render Feed Items
  function renderFeed() {
    opportunityList.innerHTML = '';
    const typeVal = filterType.value;
    const confVal = filterConfidence.value;

    const filtered = opportunitiesData.filter(item => {
      if (typeVal !== 'all' && item.opportunity_type !== typeVal) return false;
      if (confVal !== 'all' && item.confidence_level !== confVal) return false;
      return true;
    });

    if (filtered.length === 0) {
      opportunityList.innerHTML = `
        <div class="loading-state">
          <p>No counterfactual opportunities match the selected filters.</p>
        </div>
      `;
      return;
    }

    filtered.forEach(item => {
      const card = UIComponents.renderOpportunityCard(item, openOpportunityDetail);
      opportunityList.appendChild(card);
    });
  }

  // Open Opportunity Detail Modal
  async function openOpportunityDetail(id) {
    try {
      const detail = await NatilahAPI.getOpportunityDetail(id);
      modalTitle.textContent = detail.title;
      modalTypeBadge.textContent = (detail.opportunity_type || '').replace(/_/g, ' ').toUpperCase();
      modalTypeBadge.className = `badge badge-${detail.opportunity_type}`;
      modalBody.innerHTML = UIComponents.renderOpportunityDetail(detail);

      opportunityModal.classList.add('active');

      setTimeout(() => {
        const canvas = document.getElementById('utilChart');
        if (canvas && detail.utilization_series) {
          UtilizationChart.render(canvas, detail.utilization_series);
        }
      }, 50);
    } catch (err) {
      alert(`Failed to load details: ${err.message}`);
    }
  }

  // Modal Handlers
  modalClose.addEventListener('click', () => opportunityModal.classList.remove('active'));
  opportunityModal.addEventListener('click', (e) => {
    if (e.target === opportunityModal) opportunityModal.classList.remove('active');
  });

  // Filters Event Listeners
  filterType.addEventListener('change', renderFeed);
  filterConfidence.addEventListener('change', renderFeed);

  // Generate Synthetic Data Handler
  btnGenerate.addEventListener('click', async () => {
    btnGenerate.disabled = true;
    btnGenerate.textContent = 'Generating...';
    try {
      await NatilahAPI.generateData(16, 8, 50);
      await loadDashboard();
    } catch (err) {
      alert(`Generation failed: ${err.message}`);
    } finally {
      btnGenerate.disabled = false;
      btnGenerate.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg> Generate Data`;
    }
  });

  // Run Intelligence Pipeline Handler
  btnRunAnalysis.addEventListener('click', async () => {
    btnRunAnalysis.disabled = true;
    btnRunAnalysis.textContent = 'Analyzing...';
    try {
      await NatilahAPI.runAnalysis();
      await loadDashboard();
    } catch (err) {
      alert(`Analysis failed: ${err.message}`);
    } finally {
      btnRunAnalysis.disabled = false;
      btnRunAnalysis.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Run Intelligence Pipeline`;
    }
  });

  // Cost Config Modal Handlers
  btnCostConfig.addEventListener('click', async () => {
    try {
      const costs = await NatilahAPI.getCosts();
      document.getElementById('costA100').value = costs.cost_per_gpu_hour['A100-80GB'] || 2.21;
      document.getElementById('costH100').value = costs.cost_per_gpu_hour['H100-80GB'] || 3.49;
      document.getElementById('costFacility').value = costs.facility_cost_multiplier || 1.4;
      document.getElementById('costHoursPerMonth').value = costs.working_hours_per_month || 720;
      costModal.classList.add('active');
    } catch (err) {
      alert(`Failed to load costs: ${err.message}`);
    }
  });

  function closeCostModal() { costModal.classList.remove('active'); }
  costModalClose.addEventListener('click', closeCostModal);
  costCancel.addEventListener('click', closeCostModal);

  costForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const updated = {
      cost_per_gpu_hour: {
        'A100-80GB': parseFloat(document.getElementById('costA100').value),
        'H100-80GB': parseFloat(document.getElementById('costH100').value)
      },
      facility_cost_multiplier: parseFloat(document.getElementById('costFacility').value),
      working_hours_per_month: parseFloat(document.getElementById('costHoursPerMonth').value)
    };
    try {
      await NatilahAPI.updateCosts(updated);
      closeCostModal();
      await loadDashboard();
    } catch (err) {
      alert(`Failed to save cost model: ${err.message}`);
    }
  });

  // Initial Load
  loadDashboard();
});
