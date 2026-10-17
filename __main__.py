import itertools
import os
import sys
import time
import numpy as np
import pandas as pd

import comtypes.client




def check_steel_design_status(sap_model):

    ret = sap_model.DesignSteel.StartDesign()

    ret_names = sap_model.FrameObj.GetNameList(0, [])
    total_frames = ret_names[0]
    all_frame_names = ret_names[1]

    all_passed = True
    failed_members = []

    # 3. Loop through every frame and get its individual design summary
    for frame_name in all_frame_names:
        # Initialize variables required by the ByRef interface for a single item
        NumberItems = 0
        FrameName = []
        Ratio = []
        RatioType = []
        Location = []
        ComboName = []
        ErrorSummary = []
        WarningSummary = []

        # item_type = 0 specifies we are querying by a specific object Name
        item_type = 0

        ret = sap_model.DesignSteel.GetSummaryResults(
            frame_name, NumberItems, FrameName, Ratio, RatioType,
            Location, ComboName, ErrorSummary, WarningSummary, item_type
        )

        # Unpack the returned tuple from comtypes
        # Structure: (ret_code, NumberItems, FrameName, Ratio, RatioType, Location, ComboName, ErrorSummary, WarningSummary)
        ret_code = ret[0]

        if ret_code == 0:
            # Check if design data actually exists for this frame (skips non-steel or un-designed elements)
            num_items = ret[1]
            if num_items > 0:
                # Take the maximum ratio found for this specific frame across its stations
                member_ratios = ret[3]
                member_errors = ret[7]

                max_ratio = max(member_ratios)

                # Combine errors into a single readable string
                error_str = ", ".join([err.strip() for err in member_errors if err.strip()])

                # Verify pass/fail criteria
                if max_ratio > 1.0 or "OS" in error_str or "Overstressed" in error_str:
                    all_passed = False
                    failed_members.append({
                        "name": frame_name,
                        "ratio": max_ratio,
                        "error": error_str if error_str else "Exceeded Ratio"
                    })
        else:
            # ret_code != 0 usually means the member wasn't included in the steel design run
            pass
    return all_passed

def get_node_deflections(sap_model, output_nodes, output_cases):
    # 2. Set the data output context to all load combinations

    for combo in output_cases:
        ret = sap_model.Results.Setup.SetComboSelectedForOutput(combo)

    # 3. Retrieve Joint Displacements for ALL joints
    GroupElm = 2
    NumberResults = 0
    Obj = []
    Elm = []
    LoadCase = []
    StepType = []
    StepNum = []
    U1 = []
    U2 = []
    U3 = []
    R1 = []
    R2 = []
    R3 = []
    results = sap_model.Results.JointDispl("ALL",2,NumberResults,Obj,Elm,LoadCase,StepType,U1,U2,U3,R1,R2,R3)
    NumberResults = results[0]
    Elm = results[2]
    LoadCase = results[3]
    U2 = results[7]
    U3 = results[8]
    ret = results[12]

    output = np.array([Elm, LoadCase, U2, U3])

    not_in = np.isin(output[0,:], output_nodes)
    output = np.delete(output, ~not_in , axis=1)

    not_in = np.isin(output[1,:], output_cases)
    output = np.delete(output, ~not_in, axis=1)

    for i in range(len(output_nodes)):
        is_node = np.isin(output[0,:], output_nodes[i])
        output[0,is_node] = i

    for i in range(len(output_cases)):
        is_case = np.isin(output[1,:], output_cases[i])
        output[1,is_case] = i

    output = output.astype(float)

    output[0, :] = np.floor(output[0, :] / 2)
    valid_combination = ((output[0, :] < 11) & (output[0, :] == output[1, :])) | (output[0, :] == 11)

    output = np.delete(output, ~valid_combination, axis=1)

    output = output.T

    keys = output[:,:2]
    values = output[:,2:4]

    unique_keys, inverse_indices = np.unique(keys, axis=0, return_inverse=True)
    abs_values = np.abs(values)

    max_values = np.array([
        np.max(abs_values[inverse_indices == i], axis=0)
        for i in range(len(unique_keys))
    ])

    output = np.hstack((unique_keys.reshape(-1, 2), max_values))

    z = [0.0,0.0]
    zz =[z,z]
    D = np.array([zz,zz,zz,zz,zz,zz,zz,zz,zz,zz,zz,zz,zz])
    output[:,0] = output[:,0] - output[:,1]
    output[output[:,0] != 0,0] = 1

    D[output[:,1].astype(int),output[:,0].astype(int),1] = output[:,2]*3
    D[output[:,1].astype(int),output[:,0].astype(int),0] = output[:,3]*3

    return D

def analize(sap_model, output_nodes, output_cases, folder, filename, iteration_number):

    ret = sap_model.Analyze.RunAnalysis()

    if ret == 0:

        all_passed = check_steel_design_status(sap_model)

        D = get_node_deflections(sap_model, output_nodes, output_cases)

        ret = sap_model.Results.Setup.SetCaseSelectedForOutput("DEAD")

        NumberResults = 0
        LoadCase = []
        StepType = []
        StepNum = []
        Fx = []
        Fy = []
        Fz = []
        Mx = []
        My = []
        Mz = []
        gx = 0.0
        gy = 0.0
        gz = 0.0

        r = sap_model.Results.BaseReact(NumberResults,LoadCase,StepType,StepNum,Fx,Fy,Fz,Mx,My,Mz,gx,gy,gz)
        weight = r[6][0]*1000

        pass_lateral = 0.75 > max(D[11][1][1], D[12][1][1])
        pass_sway = 0.75 > max(D[0][1][1], D[1][1][1], D[2][1][1], D[3][1][1], D[4][1][1], D[5][1][1], D[6][1][1],
                               D[7][1][1], D[8][1][1], D[9][1][1], D[10][1][1])
        if 3/8 > max(D[11][1][1], D[12][1][1]):
            Gamma_lat =0.9
        else:
            Gamma_lat =1

        Dagg_list = []
        for d in D:
            Dagg_list.append(d[0][0] + d[1][0])

        C_s_list = []
        for i in range(11):
            C_s_list.append(75*weight**1.8+Gamma_lat*Dagg_list[i]*4000000)

        P_N = [1/36,2/36,3/36,4/36,5/36,6/36,5/36,4/36,3/36,2/36,1/36]

        Min_Dagg = min(Dagg_list)
        Max_Dagg = max(Dagg_list)

        Expected_Dagg = 0
        for i in range(11):
            Expected_Dagg += P_N[i] * Dagg_list[i]

        Min_Cs = min(C_s_list)
        Max_Cs = max(C_s_list)

        Expected_Cs = 0
        for i in range(11):
            Expected_Cs += P_N[i]*C_s_list[i]

        iteration_filename = filename + "_it" + str(iteration_number) + ".sdb"
        iteration_file_path = os.path.join(folder, iteration_filename)
        ret = sap_model.File.Save(iteration_file_path)
        results = [iteration_number,all_passed,bool(pass_lateral),bool(pass_sway),Gamma_lat,weight,float(Min_Dagg),float(Max_Dagg),float(Expected_Dagg),float(Min_Cs),float(Max_Cs),float(Expected_Cs)]
        print(results)
        return results
    return None

def find_best_members(sap_model, output_nodes, output_cases, member_groups, member_group_posible_members, folder, filename):

    iteration_number = 0

    results_list = []

    for combo in itertools.product(*member_group_posible_members):
        for i, group in enumerate(member_groups):
            for member_name in group:
                ret = sap_model.FrameObj.SetSection(member_name, combo[i], 0)

        results_list.append(analize(sap_model, output_nodes, output_cases, folder, filename, iteration_number))
        iteration_number += 1

    return results_list

# 1. Define the absolute path to your SAP2000 file (.sdb or .s2k)
t1 = time.time()
model_path = r"C:\Users\blake\OneDrive\Desktop\2023_it6.sdb"
output_nodes = ["DN_V2","DS_V2","DN_V3","DS_V3","DN_V4","DS_V4","DN_V5","DS_V5","DN_V6","DS_V6","DN_V7","DS_V7",
                "DN_V8","DS_V8","DN_V9","DS_V9","DN_V10","DS_V10","DN_V11","DS_V11","DN_V12","DS_V12","DN_C","DS_C"]
output_cases = ["D_N2","D_N3","D_N4","D_N5","D_N6","D_N7","D_N8","D_N9","D_N10","D_N11","D_N12","DL_south","DL_North"]
member_groups = [["222", "223","224","225","226","227","228","229","230","231","232","233","234","235"]]
member_group_posible_members = [["HSST 0.5x1.5x0.065", "HSST 0.75x1.5x0.065", "HSST 0.75x1.5x0.083"]]
#                                  "HSST 0.75x1.5x0.12","HSST 1x1.5x0.065","HSST 1x1.5x0.083","HSST 1x1.5x0.12",
#                                  "HSSS 1.5x0.065","HSSS 1.5x0.083","HSSS 1.5x0.095","HSSS 1.5x0.1","HSSS 1.5x0.109",
#                                  "HSSS 1.5x0.12","HSSS 1.5x0.25","HSSS 1.5x0.188","HSST 2x1.5x0.065","HSST 2x1.5x0.083",
#                                  "HSST 2x1.5x0.12","HSST 2x1.5x0.188"]]

save_folder = r"C:\Users\blake\OneDrive\Desktop\output_test"
filename = "2023_test"

# Ensure the destination directory exists
os.makedirs(save_folder, exist_ok=True)

# Ensure the file actually exists before starting SAP2000
if not os.path.exists(model_path):
    sys.exit(f"Error: The file at {model_path} was not found.")

# try:
# 2. Create the OAPI helper object
helper = comtypes.client.CreateObject('SAP2000v1.Helper')
helper = helper.QueryInterface(comtypes.gen.SAP2000v1.cHelper)

# 3. Start a new instance of the SAP2000 application
# (Alternatively, use helper.GetObject("CSI.SAP2000.API.SapObject") to link to an already open instance)
sap_object = helper.CreateObjectProgID("CSI.SAP2000.API.SapObject")
sap_object.ApplicationStart()

# 4. Initialize the SapModel object
sap_model = sap_object.SapModel

# 5. Open the file
ret = sap_model.File.OpenFile(model_path)

if ret == 0:

    results_list = find_best_members(sap_model, output_nodes, output_cases, member_groups, member_group_posible_members, save_folder, filename)

    results_heders = ["Iteration Number", "Steel Check", "Lateral Check", "Sway Check", "Gamma_Lat", "Weight", "Degg Min", "Degg Max", "Degg Pre", "Cs Min", "Cs Max", "Cs Pre"]
    df = pd.DataFrame(results_list, columns=results_heders)
    file_path = os.path.join(save_folder, "results.xlsx")
    df.to_excel(file_path, index=False)
    print("results list: ", results_list)
    #todo save results list to excel

else:
    print("Failed to open the file. Check file integrity or permissions.")

print("Run Time: ", time.time() - t1)

sap_object.ApplicationExit(False)