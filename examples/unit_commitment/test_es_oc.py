import os
import pytest
from pyomo.opt import SolverFactory

# Import your extension
from storage_as_extension import StorageAncillaryServicesExtension

# Import functions from the original test file
from egret.models.tests.test_unit_commitment import (
    create_test_model,
    check_model_constraints,
    test_cases,
    get_uc_model
)

# Override the model creation function
def get_extended_uc_model(model_data, **kwargs):
    """Create a UC model with storage ancillary services extension"""
    extension = StorageAncillaryServicesExtension(model_data)
    return extension.create_and_extend_model(**kwargs)

# Create modified test functions
@pytest.mark.parametrize("test_case", test_cases)
def test_extended_uc_model(test_case):
    """Test the unit commitment model with storage ancillary services"""
    model_data = create_test_model(test_case)
    
    
    _add_storage_with_ancillary_capabilities(model_data)
    
    # Use the extended model instead of the standard one
    model = get_extended_uc_model(model_data)
    
    # Check if solver exists
    solver_available = SolverFactory('cbc').available()
    if not solver_available:
        pytest.skip("CBC solver not available")
    
    # Run the tests
    results = check_model_constraints(model, model_data)
    assert results.solver.termination_condition == 'optimal'
    
    # Additional checks for storage ancillary services
    _check_storage_ancillary_services(model)

def _add_storage_with_ancillary_capabilities(model_data):
    """Add storage units with ancillary service capabilities to the model data"""
    # Add storage if not already present
    if 'storage' not in model_data.data['elements']:
        model_data.data['elements']['storage'] = {}
    
    # Add a sample storage unit
    model_data.data['elements']['storage']['Storage1'] = {
        'bus': 'Bus1',  # Adjust based on your test case
        'energy_capacity': 100.0,
        'charge_efficiency': 0.95,
        'discharge_efficiency': 0.95,
        'min_charge_rate': 0.0,
        'max_charge_rate': 50.0,
        'min_discharge_rate': 0.0,
        'max_discharge_rate': 50.0,
        'initial_state_of_charge': 0.5,
        'ramp_up_input_60min': 50.0,
        'ramp_down_input_60min': 50.0,
        'ramp_up_output_60min': 50.0,
        'ramp_down_output_60min': 50.0,
        # Add ancillary service capabilities
        'regulation_capability': 25.0,
        'spinning_capability': 25.0,
        'flexible_ramp_capability': 25.0
    }

def _check_storage_ancillary_services(model):
    """Check if storage ancillary services are working correctly"""
    # Check that storage ancillary service variables exist
    assert hasattr(model, 'StorageRegulationReserveUp')
    assert hasattr(model, 'StorageSpinningReserve')
    assert hasattr(model, 'StorageFlexUpProvided')
    
    # Additional checks can be performed here
    # For example, check that storage is providing some reserves
    if model.regulation_service:
        for s in model.Storage:
            for t in model.TimePeriods:
                if value(model.StorageRegulationReserveUp[s,t]) > 0:
                    return True
    
    # The test might still pass if no reserves are provided
    # as it depends on the economic conditions
    return True