import argparse
from common import sm_client, create_model, create_endpoint_config, INSTANCE_TYPES
from create_autoscaling import create_autoscaling


def create_endpoint(endpoint_config_name):
    from time import gmtime, strftime
    endpoint_name = 'docling-serve-' + strftime("%Y-%m-%d-%H-%M-%S", gmtime())
    print('Endpoint name: ' + endpoint_name)

    create_endpoint_response = sm_client.create_endpoint(
        EndpointName=endpoint_name,
        EndpointConfigName=endpoint_config_name)
    print('Endpoint Arn: ' + create_endpoint_response['EndpointArn'])

    resp = sm_client.describe_endpoint(EndpointName=endpoint_name)
    status = resp['EndpointStatus']
    print("Endpoint Status: " + status)

    print('Waiting for {} endpoint to be in service...'.format(endpoint_name))
    waiter = sm_client.get_waiter('endpoint_in_service')
    waiter.wait(EndpointName=endpoint_name)
    return endpoint_name


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create a SageMaker endpoint')
    parser.add_argument('--env', type=str, choices=['dev', 'prod'], required=True,
                        help='Environment (dev or prod)')
    parser.add_argument('--image-version', type=str, required=True,
                        help='Docker image version tag (e.g. v1.13.1)')
    args = parser.parse_args()

    model_name = create_model(args.image_version)
    endpoint_config_name = create_endpoint_config(model_name, INSTANCE_TYPES[args.env])
    endpoint_name = create_endpoint(endpoint_config_name)
    create_autoscaling(endpoint_name)
