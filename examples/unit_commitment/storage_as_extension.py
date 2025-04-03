import pyomo.environ as pe
from egret.models.unit_commitment import create_tight_unit_commitment_model, solve_unit_commitment

class StorageAncillaryServicesExtension:
    def __init__(self, model_data):
        self.model_data = model_data
        self.uc_model = None
        
    def create_and_extend_model(self, **kwargs):
        # First create the standard UC model using EGRET
        self.uc_model = create_tight_unit_commitment_model(self.model_data, **kwargs)
        
        # Now extend the model with storage ancillary services
        self._add_storage_ancillary_services()
        
        return self.uc_model
    
    def solve(self, solver, **kwargs):
        # Solve the extended model using EGRET's solver interface
        return solve_unit_commitment(self.model_data, solver, model=self.uc_model, **kwargs)
        
    def _add_storage_ancillary_services(self):
        # Add variables and constraints for storage ancillary services
        self._add_storage_regulation_services()
        self._add_storage_spinning_reserve()
        self._add_storage_flexible_ramping()
        self._modify_objective_function()
    
    def _add_storage_regulation_services(self):
        m = self.uc_model
        
        # 1. Add regulation capability variables for storage
        m.StorageRegulationUpCapability = pe.Param(m.Storage, m.TimePeriods, 
                                                 initialize=self._get_storage_reg_up_capability)
        m.StorageRegulationDnCapability = pe.Param(m.Storage, m.TimePeriods, 
                                                 initialize=self._get_storage_reg_dn_capability)
        
        # 2. Add regulation provision variables
        m.StorageRegulationReserveUp = pe.Var(m.Storage, m.TimePeriods, within=pe.NonNegativeReals)
        m.StorageRegulationReserveDn = pe.Var(m.Storage, m.TimePeriods, within=pe.NonNegativeReals)
        
        # 3. Add regulation eligibility flags for storage units
        m.StorageRegulationOn = pe.Var(m.Storage, m.TimePeriods, within=pe.Binary)
        
        # 4. Limit regulation provision based on capability
        def storage_reg_up_limit_rule(m, s, t):
            return m.StorageRegulationReserveUp[s,t] <= m.StorageRegulationUpCapability[s,t] * m.StorageRegulationOn[s,t]
        m.StorageRegulationUpLimit = pe.Constraint(m.Storage, m.TimePeriods, rule=storage_reg_up_limit_rule)
        
        def storage_reg_dn_limit_rule(m, s, t):
            return m.StorageRegulationReserveDn[s,t] <= m.StorageRegulationDnCapability[s,t] * m.StorageRegulationOn[s,t]
        m.StorageRegulationDnLimit = pe.Constraint(m.Storage, m.TimePeriods, rule=storage_reg_dn_limit_rule)
        
        # 5. Modify existing regulation requirement constraints to include storage
        if hasattr(m, 'EnforceZonalRegulationUpRequirement'):
            for idx, constr in m.EnforceZonalRegulationUpRequirement.items():
                rz, t = idx
                expr = constr.expr
                # Add storage regulation contribution to existing constraint
                storage_contribution = sum(m.StorageRegulationReserveUp[s,t] 
                                         for s in self._get_storage_in_reg_zone(rz))
                # Create and add new constraint with storage contribution
                new_expr = expr.expr + storage_contribution >= expr.upper
                m.EnforceZonalRegulationUpRequirement[idx] = new_expr
    
    def _add_storage_spinning_reserve(self):
        m = self.uc_model
        
        # 1. Add spinning reserve variables for storage
        m.StorageSpinningReserve = pe.Var(m.Storage, m.TimePeriods, within=pe.NonNegativeReals)
        
        # 2. Add constraints limiting spinning reserve provision
        def storage_spin_limit_rule(m, s, t):
            # Limit based on available capacity and ramp rate
            discharge_capacity = m.MaximumPowerOutputStorage[s] - m.PowerOutputStorage[s,t]
            ramp_capacity = m.ScaledNominalRampUpLimitStorageOutput[s]
            # Can only provide spin when discharging or idle (not charging)
            return m.StorageSpinningReserve[s,t] <= min(discharge_capacity, ramp_capacity) * (1 - m.InputStorage[s,t])
        m.StorageSpinningReserveLimit = pe.Constraint(m.Storage, m.TimePeriods, rule=storage_spin_limit_rule)
        
        # 3. Modify existing spinning reserve requirement constraints to include storage
        if hasattr(m, 'EnforceZonalSpinningReserveRequirement'):
            for idx, constr in m.EnforceZonalSpinningReserveRequirement.items():
                rz, t = idx
                expr = constr.expr
                # Add storage spin contribution to existing constraint
                storage_contribution = sum(m.StorageSpinningReserve[s,t] 
                                         for s in self._get_storage_in_spin_zone(rz))
                # Create and add new constraint with storage contribution
                new_expr = expr.expr + storage_contribution >= expr.upper
                m.EnforceZonalSpinningReserveRequirement[idx] = new_expr
    
    def _add_storage_flexible_ramping(self):
        m = self.uc_model
        
        # 1. Add flexible ramping variables for storage
        m.StorageFlexUpProvided = pe.Var(m.Storage, m.TimePeriods, within=pe.NonNegativeReals)
        m.StorageFlexDnProvided = pe.Var(m.Storage, m.TimePeriods, within=pe.NonNegativeReals)
        
        # 2. Add constraints limiting flexible ramping provision
        def storage_flex_up_limit_rule(m, s, t):
            if t == m.TimePeriods.last():
                return m.StorageFlexUpProvided[s,t] == 0
            
            # Headroom for additional discharge in next period
            headroom = m.MaximumPowerOutputStorage[s] - m.PowerOutputStorage[s,t]
            # Room to reduce charging in next period
            charge_reduction = m.PowerInputStorage[s,t]
            # Ramp rate limit
            ramp_limit = m.FlexRampMinutes * (m.NominalRampUpLimitStorageOutput[s]/60.)
            
            return m.StorageFlexUpProvided[s,t] <= min(headroom + charge_reduction, ramp_limit)
        m.StorageFlexUpLimit = pe.Constraint(m.Storage, m.TimePeriods, rule=storage_flex_up_limit_rule)
        
        # 3. Modify existing flex ramp requirement constraints
        if hasattr(m, 'ZonalFlexUpRequirementConstr'):
            for idx, constr in m.ZonalFlexUpRequirementConstr.items():
                rz, t = idx
                expr = constr.expr
                # Add storage flex contribution to existing constraint
                storage_contribution = sum(m.StorageFlexUpProvided[s,t] 
                                         for s in self._get_storage_in_flex_zone(rz))
                # Create and add new constraint with storage contribution
                new_expr = expr.expr + storage_contribution >= expr.upper
                m.ZonalFlexUpRequirementConstr[idx] = new_expr
    
    def _modify_objective_function(self):
        m = self.uc_model
        
        # Add storage ancillary service costs/revenues to the objective
        def storage_reg_cost_rule(m, s, t):
            return m.RegulationOfferMarginalCost.default * m.TimePeriodLengthHours * (
                m.StorageRegulationReserveUp[s,t] + m.StorageRegulationReserveDn[s,t])
        m.StorageRegulationCost = pe.Expression(m.Storage, m.TimePeriods, rule=storage_reg_cost_rule)
        
        def storage_spin_cost_rule(m, s, t):
            return m.SpinningReservePrice.default * m.TimePeriodLengthHours * m.StorageSpinningReserve[s,t]
        m.StorageSpinningReserveCost = pe.Expression(m.Storage, m.TimePeriods, rule=storage_spin_cost_rule)
        
        # Modify the generation stage cost to include storage ancillary services
        for st in m.StageSet:
            old_expr = m.GenerationStageCost[st].expr
            storage_as_cost = sum(
                sum(m.StorageRegulationCost[s,t] + m.StorageSpinningReserveCost[s,t] 
                    for s in m.Storage) 
                for t in m.GenerationTimeInStage[st]
            )
            # Create and replace with new expression
            m.GenerationStageCost[st] = old_expr + storage_as_cost
    
    def _get_storage_in_reg_zone(self, zone):
        """Return storage units in the given regulation zone"""
        # Map storage to zones based on bus locations
        storage_by_zone = {}
        for s in self.uc_model.Storage:
            # Find bus for storage s
            for b in self.uc_model.Buses:
                if s in self.uc_model.StorageAtBus[b]:
                    # Find zone for bus b
                    for z in self.uc_model.RegulationZones:
                        # Logic to determine if bus b is in zone z
                        # (would depend on how zones are defined in your data)
                        if self._is_bus_in_zone(b, z):
                            if z not in storage_by_zone:
                                storage_by_zone[z] = []
                            storage_by_zone[z].append(s)
        
        return storage_by_zone.get(zone, [])
    
    def _get_storage_in_spin_zone(self, zone):
        """Return storage units in the given spinning reserve zone"""
        # Similar to _get_storage_in_reg_zone but for spinning reserve zones
        # Implementation would depend on your zone definitions
        return self._get_storage_in_zone(zone, self.uc_model.SpinningReserveZones)
    
    def _get_storage_in_flex_zone(self, zone):
        """Return storage units in the given flexible ramp zone"""
        # Similar to _get_storage_in_reg_zone but for flex ramp zones
        # Implementation would depend on your zone definitions
        return self._get_storage_in_zone(zone, self.uc_model.FlexRampZones)
    
    def _get_storage_in_zone(self, zone, zone_set):
        """Generic method to get storage in a zone"""
        storage_by_zone = {}
        for s in self.uc_model.Storage:
            for b in self.uc_model.Buses:
                if s in self.uc_model.StorageAtBus[b]:
                    if self._is_bus_in_zone(b, zone):
                        if zone not in storage_by_zone:
                            storage_by_zone[zone] = []
                        storage_by_zone[zone].append(s)
        return storage_by_zone.get(zone, [])
    
    def _is_bus_in_zone(self, bus, zone):
        """Determine if a bus is in a zone"""
        # This implementation depends on how zones are defined in your data
        # A simple implementation might be:
        zone_data = self.model_data.data['elements']['zone'][zone]
        if 'buses' in zone_data:
            return bus in zone_data['buses']
        return False
    
    def _get_storage_reg_up_capability(self, m, s, t):
        """Return regulation up capability for storage unit s at time t"""
        # This could come from your model_data or be calculated based on 
        # storage characteristics (e.g., ramp rate * regulation time period)
        return min(m.MaximumPowerOutputStorage[s], 
                  m.NominalRampUpLimitStorageOutput[s]/60. * m.RegulationMinutes)
    
    def _get_storage_reg_dn_capability(self, m, s, t):
        """Return regulation down capability for storage unit s at time t"""
        # Similar to regulation up capability
        return min(m.MaximumPowerOutputStorage[s], 
                  m.NominalRampDownLimitStorageOutput[s]/60. * m.RegulationMinutes)