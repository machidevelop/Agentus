/**
 * API client wrapper for Natilah V1 REST API endpoints.
 */

const API_BASE = '/api';

class NatilahAPI {
  static async getSummary() {
    const res = await fetch(`${API_BASE}/dashboard/summary`);
    if (!res.ok) throw new Error('Failed to fetch summary');
    return await res.json();
  }

  static async getOpportunities() {
    const res = await fetch(`${API_BASE}/opportunities`);
    if (!res.ok) throw new Error('Failed to fetch opportunities');
    return await res.json();
  }

  static async getOpportunityDetail(id) {
    const res = await fetch(`${API_BASE}/opportunities/${id}`);
    if (!res.ok) throw new Error('Failed to fetch opportunity detail');
    return await res.json();
  }

  static async generateData(numNodes = 16, gpusPerNode = 8, numJobs = 50) {
    const res = await fetch(`${API_BASE}/ingestion/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ num_nodes: numNodes, gpus_per_node: gpusPerNode, num_jobs: numJobs })
    });
    if (!res.ok) throw new Error('Failed to generate dataset');
    return await res.json();
  }

  static async runAnalysis() {
    const res = await fetch(`${API_BASE}/analysis/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    if (!res.ok) throw new Error('Failed to run analysis pipeline');
    return await res.json();
  }

  static async getCosts() {
    const res = await fetch(`${API_BASE}/config/costs`);
    if (!res.ok) throw new Error('Failed to fetch cost config');
    return await res.json();
  }

  static async updateCosts(config) {
    const res = await fetch(`${API_BASE}/config/costs`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
    if (!res.ok) throw new Error('Failed to update cost config');
    return await res.json();
  }
}
