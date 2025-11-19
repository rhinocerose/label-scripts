import csv
import argparse


choices = ["c", "r"]

def options():
    parser = argparse.ArgumentParser(description='Script to convert LCSC CSV files')
    parser.add_argument('-i', '--input',
                        type=str, required=True,
                        help='Name of input file')
    parser.add_argument('-t', '--type', choices = choices,
                        type=str.lower, required=True,
                        help='Type of input')
    args = parser.parse_args()
    return args.input, args.type


def read_into_list(input_file):	
	with open(input_file, 'r') as inp:
		read = csv.reader(inp)
		arr = list(read)	
	return arr
    
 
def parse_data(input_arr, component_type):
    output_arr = []
    if component_type == "c":
        output_arr.append(["LCSC Number", "MPN", "Capacitance", "Voltage", "Tolerance", "Dielectric", "Size"])
        for line in input_arr:
            stat = line[5].split()
            temp = [line[0], line[1], stat[1], stat[0], stat[3], stat[2], line[4]]
            output_arr.append(temp)
    elif component_type == "r":
        output_arr = [["LCSC Number", "MPN", "Resistance", "Power", "Tolerance", "Size"]]   
        for line in input_arr:
            stat = line[5].split
            temp = [line[0], line[1], stat[1], stat[0], stat[3], line[4]]
            output_arr.append(temp)    
    return output_arr        

def write_csv()
        
if __name__ == "__main__":
    input_file, component_type = options()
    arr = read_into_list(input_file)
    out_arr = parse_data(arr, component_type)
    print(out_arr)