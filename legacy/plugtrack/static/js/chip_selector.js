/**
 * Chip selector for PlugTrack session insights
 * Implements the logic for selecting up to 3 inline chips per session row
 */

function selectInlineChips(metrics, settings = {}) {
    const chips = [];
    
    // 1. Efficiency chip (priority 1)
    if (metrics.efficiency_used !== null && metrics.efficiency_used !== undefined) {
        // Phase 5.2: Include confidence information
        const confidenceLevel = metrics.efficiency_confidence || 'unknown';
        const confidenceReasons = metrics.confidence_reasons || [];
        
        const efficiencyChip = {
            type: 'efficiency',
            value: metrics.efficiency_used.toFixed(1),
            unit: 'mi/kWh',
            colorClass: getEfficiencyColorClass(metrics.efficiency_used),
            muted: metrics.low_confidence || false,
            tooltip: getEfficiencyTooltip(metrics, metrics.low_confidence, confidenceLevel, confidenceReasons),
            confidenceBadge: getConfidenceBadge(confidenceLevel, confidenceReasons)
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
        // Phase 5.1: Try £/10% SOC first
        if (metrics.cost_per_10_percent > 0) {
            const costPer10PercentChip = {
                type: 'cost_per_10_percent',
                value: metrics.cost_per_10_percent.toFixed(2),
                unit: '£/10%',
                colorClass: 'chip--secondary',
                muted: false,
                tooltip: `Cost per 10% SOC: £${metrics.cost_per_10_percent.toFixed(2)}`
            };
            chips.push(costPer10PercentChip);
        } else if (metrics.avg_power_kw > 0) {
            // Fall back to average power
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
        // Phase 5.1: Try Home ROI delta first
        if (metrics.home_roi_delta !== null && metrics.home_roi_delta !== undefined) {
            const homeRoiChip = {
                type: 'home_roi_delta',
                value: (metrics.home_roi_delta >= 0 ? '+' : '') + metrics.home_roi_delta.toFixed(1),
                unit: 'p/mi vs home',
                colorClass: metrics.home_roi_delta <= 0 ? 'chip--green' : 'chip--red',
                muted: false,
                tooltip: `Cost delta vs 30-day home baseline: ${(metrics.home_roi_delta >= 0 ? '+' : '')}${metrics.home_roi_delta.toFixed(1)}p/mi`
            };
            chips.push(homeRoiChip);
        } else if (metrics.percent_per_kwh > 0) {
            // Fall back to percent per kWh
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

function getConfidenceColorClass(confidenceLevel) {
    switch (confidenceLevel) {
        case 'high': return 'chip--green';
        case 'medium': return 'chip--amber';
        case 'low': return 'chip--red';
        default: return 'chip--secondary';
    }
}

function getConfidenceBadge(confidenceLevel, reasons) {
    if (!reasons || reasons.length === 0) return '';
    
    const symbol = confidenceLevel === 'low' ? '⚠️' : 
                   confidenceLevel === 'medium' ? '⚡' : '✅';
    const tooltip = `Confidence: ${confidenceLevel}. Issues: ${reasons.join(', ')}`;
    
    return `<span class="confidence-badge" title="${tooltip}">${symbol}</span>`;
}

function getCostPerMileColorClass(costPerMile, thresholdPpm) {
    if (!thresholdPpm || thresholdPpm <= 0) return 'chip--secondary';
    
    const costPerMileP = costPerMile * 100;
    if (costPerMileP <= thresholdPpm * 0.75) return 'chip--green';
    if (costPerMileP <= thresholdPpm * 1.25) return 'chip--amber';
    return 'chip--red';
}

function getEfficiencyTooltip(metrics, lowConfidence, confidenceLevel, confidenceReasons) {
    let tooltip = `Miles gained per kWh: ${metrics.miles_gained ? metrics.miles_gained.toFixed(1) : '0.0'} mi / ${metrics.efficiency_used.toFixed(1)} mi/kWh`;
    
    // Phase 5.2: Add confidence information
    if (confidenceLevel && confidenceLevel !== 'high') {
        tooltip += `\nConfidence: ${confidenceLevel}`;
        if (confidenceReasons && confidenceReasons.length > 0) {
            tooltip += `\nIssues: ${confidenceReasons.join(', ')}`;
        }
    }
    
    return tooltip;
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
        const confidenceBadge = chip.confidenceBadge || '';
        
        return `
            <span class="chip ${colorClass}${mutedClass}" 
                  title="${chip.tooltip}">
                ${chip.value} ${chip.unit}${confidenceBadge}
            </span>
        `;
    }).join('');
    
    container.innerHTML = chipsHtml;
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { selectInlineChips, renderInlineChips };
}
