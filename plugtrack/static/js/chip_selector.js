/**
 * Chip selector for PlugTrack session insights
 * Implements the logic for selecting up to 3 inline chips per session row
 */

function selectInlineChips(metrics, settings = {}) {
    const chips = [];
    
    // 1. Efficiency chip (priority 1)
    if (metrics.efficiency_used !== null && metrics.efficiency_used !== undefined) {
        const efficiencyChip = {
            type: 'efficiency',
            value: metrics.efficiency_used.toFixed(1),
            unit: 'mi/kWh',
            colorClass: getEfficiencyColorClass(metrics.efficiency_used),
            muted: metrics.low_confidence || false,
            tooltip: getEfficiencyTooltip(metrics, metrics.low_confidence)
        };
        chips.push(efficiencyChip);
    }
    
    // 2. Cost per mile chip (priority 2)
    if (metrics.cost_per_mile !== null && metrics.cost_per_mile !== undefined) {
        const costPerMileChip = {
            type: 'cost_per_mile',
            value: (metrics.cost_per_mile * 100).toFixed(1),
            unit: 'p/mi',
            colorClass: getCostPerMileColorClass(metrics.cost_per_mile, metrics.threshold_ppm),
            muted: metrics.cost_per_mile === 0,
            tooltip: getCostPerMileTooltip(metrics)
        };
        chips.push(costPerMileChip);
    }
    
    // 3. Petrol comparison chip (priority 3) - only if threshold available
    if (metrics.threshold_ppm > 0 && metrics.is_cheaper_than_petrol !== null) {
        const petrolChip = {
            type: 'petrol_compare',
            value: metrics.is_cheaper_than_petrol ? '✓ cheaper' : '✖ dearer',
            unit: '',
            colorClass: metrics.is_cheaper_than_petrol ? 'chip--green' : 'chip--red',
            muted: false,
            tooltip: getPetrolCompareTooltip(metrics)
        };
        chips.push(petrolChip);
    }
    
    // 4. Fill remaining slots with secondary metrics (max 3 total)
    if (chips.length < 3) {
        // Try average power
        if (metrics.avg_power_kw > 0) {
            const avgPowerChip = {
                type: 'avg_power',
                value: metrics.avg_power_kw.toFixed(1),
                unit: 'kW',
                colorClass: 'chip--primary',
                muted: false,
                tooltip: `Average power: ${metrics.avg_power_kw.toFixed(1)} kW`
            };
            chips.push(avgPowerChip);
        }
    }
    
    if (chips.length < 3) {
        // Try percent per kWh
        if (metrics.percent_per_kwh > 0) {
            const percentPerKwhChip = {
                type: 'percent_per_kwh',
                value: metrics.percent_per_kwh.toFixed(1),
                unit: '%/kWh',
                colorClass: 'chip--secondary',
                muted: false,
                tooltip: `Battery percentage added per kWh: ${metrics.percent_per_kwh.toFixed(1)}%/kWh`
            };
            chips.push(percentPerKwhChip);
        }
    }
    
    // Ensure we don't exceed 3 chips
    return chips.slice(0, 3);
}

function getEfficiencyColorClass(efficiency) {
    if (efficiency < 2.0) return 'chip--red';
    if (efficiency <= 3.0) return 'chip--amber';
    return 'chip--green';
}

function getCostPerMileColorClass(costPerMile, thresholdPpm) {
    if (!thresholdPpm || thresholdPpm <= 0) return 'chip--secondary';
    
    const costPerMileP = costPerMile * 100;
    if (costPerMileP <= thresholdPpm * 0.75) return 'chip--green';
    if (costPerMileP <= thresholdPpm * 1.25) return 'chip--amber';
    return 'chip--red';
}

function getEfficiencyTooltip(metrics, lowConfidence) {
    if (lowConfidence) {
        return `Short window (Δ${metrics.delta_miles || 'N/A'} mi, ${metrics.charge_delivered_kwh || 'N/A'} kWh) — noisy.`;
    }
    return `Miles gained per kWh: ${metrics.miles_gained ? metrics.miles_gained.toFixed(1) : '0.0'} mi / ${metrics.efficiency_used.toFixed(1)} mi/kWh`;
}

function getCostPerMileTooltip(metrics) {
    if (metrics.cost_per_mile === 0) {
        return 'Total cost ÷ miles from anchor window.';
    }
    return `Cost per mile: £${metrics.cost_per_mile ? metrics.cost_per_mile.toFixed(3) : '0.000'} = ${(metrics.cost_per_mile * 100).toFixed(1)}p/mi`;
}

function getPetrolCompareTooltip(metrics) {
    // This would need to be calculated based on user's petrol baseline settings
    // For now, use a simplified version
    if (metrics.threshold_ppm > 0) {
        return `Petrol eq: ${metrics.threshold_ppm.toFixed(1)} p/mi threshold.`;
    }
    return 'Petrol comparison not available';
}

function renderInlineChips(container, chips) {
    if (!chips || chips.length === 0) {
        container.innerHTML = '<div class="text-center text-muted"><small>No insights available</small></div>';
        return;
    }
    
    const chipsHtml = chips.map(chip => {
        const mutedClass = chip.muted ? ' chip--muted' : '';
        const colorClass = chip.colorClass || 'chip--secondary';
        
        return `
            <span class="chip ${colorClass}${mutedClass}" 
                  title="${chip.tooltip}">
                ${chip.value} ${chip.unit}
            </span>
        `;
    }).join('');
    
    container.innerHTML = chipsHtml;
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { selectInlineChips, renderInlineChips };
}
